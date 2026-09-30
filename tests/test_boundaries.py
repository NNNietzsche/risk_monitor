import asyncio
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from tests.support import monitor_request as MonitorCreate, create_store as Store, sample, prepare
from tests.recorded_provider import MockProvider

PAYLOAD = {"kind":"vessel","name":"边界测试","imo":"9074729"}


def test_foreign_origin_cannot_mutate(tmp_path):
    with TestClient(create_app(tmp_path / "origin.db")) as c:
        assert c.post("/api/v1/monitors", json=PAYLOAD, headers={"origin":"https://untrusted.example"}).status_code == 403
        assert c.get("/api/v1/monitors").json() == []
        assert c.post("/api/v1/regions", json={"name":"A","west":1,"east":2,"south":1,"north":2}, headers={"origin":"http://127.0.0.1:3000"}).status_code == 201
        assert c.get("/api/v1/health", headers={"host":"untrusted.example"}).status_code == 400


def test_future_observation_does_not_become_current(tmp_path):
    class FutureProvider(MockProvider):
        def fetch(self, target, now):
            return super().fetch(target, now + timedelta(hours=1))
    store = Store(tmp_path / "future.db")
    store.providers["recorded-v1"] = FutureProvider()
    m = store.create_monitor(MonitorCreate(**PAYLOAD))
    assert sample(store, m["id"], "inside")["outcome"] == "future"
    assert store.detail(m["id"])["latest"] is None


def test_rule_failure_retains_raw_and_rolls_back_results(tmp_path, monkeypatch):
    store = Store(tmp_path / "atomic.db")
    m = store.create_monitor(MonitorCreate(**PAYLOAD))
    def fail(*args):
        raise RuntimeError("test evaluation failure")
    monkeypatch.setattr("backend.store.evaluate", fail)
    with pytest.raises(RuntimeError):
        sample(store, m["id"], "inside")
    result = store.detail(m["id"])
    assert result["raw_records"][0]["outcome"] == "processing_error"
    assert result["observations"] == []
    assert result["evaluations"] == []
    assert store.events()["total"] == 0


def test_real_scheduler_lifespan_runs_a_cycle(tmp_path):
    app = create_app(tmp_path / "scheduler.db", interval=5)
    prepare(app.state.store)
    m = app.state.store.create_monitor(MonitorCreate(**PAYLOAD))
    async def run():
        async with app.router.lifespan_context(app):
            await asyncio.sleep(5.4)
        assert app.state.store.detail(m["id"])["latest"] is not None
    asyncio.run(run())


def test_contract_describes_responses(tmp_path):
    schema = create_app(tmp_path / "schema.db").openapi()
    assert schema["paths"]["/api/v1/events"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/EventPage")
    assert "raw_record" in schema["components"]["schemas"]["EventDetail"]["properties"]

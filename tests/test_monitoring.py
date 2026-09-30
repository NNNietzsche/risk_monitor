from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.models import RuleChange
from tests.support import monitor_request as MonitorCreate, sample, create_store as Store
from backend.store import encoded
from tests.recorded_provider import MockProvider
from backend.rules import evaluate


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


def vessel(store):
    return store.create_monitor(MonitorCreate(kind="vessel", name="测试船舶", imo="9074729"))


def flight(store, **changes):
    values = dict(kind="flight", name="测试航班", carrier="RM", flight_number="101", service_date="2026-09-09",
                  departure="HND", arrival="PVG", scheduled_departure="2026-09-09T10:00:00+09:00",
                  scheduled_arrival="2026-09-09T13:00:00+09:00")
    return store.create_monitor(MonitorCreate(**(values | changes)))


def event_types(store, monitor_id):
    return [x["type"] for x in reversed(store.events(monitor_id=monitor_id)["items"])]


def test_vessel_round_trip_and_reentry(store):
    m = vessel(store)
    for scenario in ("outside", "inside", "inside", "outside", "inside"):
        sample(store, m["id"], scenario)
    assert event_types(store, m["id"]) == ["vessel.entered_region", "vessel.exited_region", "vessel.entered_region"]


def test_first_seen_and_boundary(store):
    m = vessel(store)
    sample(store, m["id"], "boundary")
    assert event_types(store, m["id"]) == ["vessel.first_seen_inside"]


def test_flight_delay_recovery(store):
    m = flight(store)
    for scenario in ("on_time", "delayed", "delayed", "recovered"):
        sample(store, m["id"], scenario)
    assert event_types(store, m["id"]) == ["flight.delay_exceeded", "flight.delay_recovered"]


@pytest.mark.parametrize("basis", ["departure", "arrival"])
def test_strict_threshold_and_actual_precedence(store, basis):
    m = flight(store, delay_basis=basis)
    provider=MockProvider();provider.scenario="delayed"
    data = provider.fetch(m, datetime.now(timezone.utc))["observation"]
    scheduled = datetime.fromisoformat(m["flight"]["scheduled_" + basis])
    data["estimated_" + basis] = (scheduled + timedelta(minutes=60)).isoformat()
    assert evaluate(m, data)[3] == []
    data["actual_" + basis] = (scheduled + timedelta(minutes=61)).isoformat()
    result = evaluate(m, data)
    assert result[3][0][0] == "flight.delay_exceeded"
    assert result[2]["time_basis"] == "actual_" + basis
    assert result[2]["delay_minutes"] == 61


def test_cancel_divert_restore(store):
    m = flight(store)
    for scenario in ("cancelled", "cancelled", "diverted", "recovered"):
        sample(store, m["id"], scenario)
    assert event_types(store, m["id"]) == ["flight.cancelled", "flight.diverted", "flight.status_restored"]


@pytest.mark.parametrize("scenario", ["missing", "failure"])
def test_bad_data_retains_previous_state(store, scenario):
    m = vessel(store)
    sample(store, m["id"], "outside")
    sample(store, m["id"], scenario)
    current = store.detail(m["id"])
    assert current["health"] != "ok"
    assert current["state"]["inside"] is False
    assert len(current["raw_records"]) == 2
    assert store.events()["total"] == 0


def test_stale_first_observation_is_unknown(store):
    m = vessel(store)
    assert sample(store, m["id"], "stale")["outcome"] == "stale"
    assert store.detail(m["id"])["latest"] is None


def test_duplicate_and_old_are_ignored(store):
    m = vessel(store)
    sample(store, m["id"], "inside")
    assert sample(store, m["id"], "duplicate")["outcome"] == "duplicate"
    assert sample(store, m["id"], "out_of_order")["outcome"] == "out_of_order"
    assert len(store.detail(m["id"])["observations"]) == 1
    assert store.events()["total"] == 1


def test_event_provenance_and_reopen(store):
    m = vessel(store)
    sample(store, m["id"], "outside")
    previous = store.detail(m["id"])["latest"]
    event_id = sample(store, m["id"], "inside")["events"][0]
    detail = Store(store.path).event_detail(event_id)
    assert detail["previous_observation"]["id"] == previous["id"]
    assert detail["previous_observation"]["data"] == previous["data"]
    raw = detail["raw_record"]
    assert hashlib.sha256(encoded(raw["payload"]).encode()).hexdigest() == raw["sha256"]
    assert detail["evidence"]["rule_version"] == 1
    assert detail["evidence"]["regions"][0]["version"] == 1
    assert detail["evidence"]["raw_sha256"] == raw["sha256"]


def test_concurrent_polls_do_not_duplicate_transition(store):
    m = vessel(store)
    sample(store, m["id"], "outside")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: sample(store, m["id"], "inside"), range(4)))
    assert event_types(store, m["id"]) == ["vessel.entered_region"]


def test_rule_version_preserves_old_evidence(store):
    m = flight(store)
    event_id = sample(store, m["id"], "delayed")["events"][0]
    store.change_rule(m["id"], RuleChange(threshold_minutes=120))
    assert store.event_detail(event_id)["rule"]["config"]["threshold_minutes"] == 60
    assert store.detail(m["id"])["rule"]["version"] == 2


def test_aircraft_and_flight_instances_are_distinct(store):
    a = flight(store, aircraft_registration="JA-MOCK")
    b = flight(store, aircraft_registration="JA-MOCK", flight_number="102")
    assert a["flight_id"] != b["flight_id"]
    assert a["flight"]["aircraft_id"] == b["flight"]["aircraft_id"]


def test_missing_flight_timing_is_not_on_time(store):
    m = flight(store)
    assert sample(store, m["id"], "missing")["outcome"] == "missing"
    assert store.detail(m["id"])["state"] == {}


def test_normalization_failure_keeps_raw(store):
    class BadProvider(MockProvider):
        def normalize(self, payload, target):
            raise ValueError("invalid fixture")
    store.providers["recorded-v1"] = BadProvider()
    m = vessel(store)
    assert sample(store, m["id"], "inside")["outcome"] == "invalid"
    assert store.detail(m["id"])["raw_records"][0]["error"] == "invalid fixture"


def test_naive_schedule_and_date_mismatch_rejected(store):
    with pytest.raises(ValueError):
        flight(store, scheduled_departure="2026-09-09T10:00:00")
    with pytest.raises(ValueError):
        flight(store, service_date="2026-09-10")


def test_region_bounds_api(tmp_path):
    with TestClient(create_app(tmp_path / "api.db")) as client:
        assert client.post("/api/v1/regions", json={"name":"跨日界线","west":170,"east":-170,"south":10,"north":20}).status_code == 422
        assert client.post("/api/v1/regions", json={"name":"区域B","west":120,"east":130,"south":20,"north":30}).status_code == 201

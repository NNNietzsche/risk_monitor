from fastapi.testclient import TestClient
from backend.app import create_app
from tests.support import seed, sample, monitor_request as MonitorCreate


def test_timeline_snapshot_pagination_stays_stable_during_polling(tmp_path):
    app = create_app(tmp_path / 'timeline.db', interval=0)
    with TestClient(app) as client:
        seed(app.state.store)
        monitor = app.state.store.monitors()[0]
        for _ in range(21):
            sample(app.state.store, monitor['id'], 'sequence')
        first = client.get('/api/v1/timeline').json()
        assert len(first['items']) == 10 and first['total'] == 25
        initial_ids = [r['id'] for r in app.state.dashboard.timeline(limit=100)['items']]
        sample(app.state.store, monitor['id'], 'sequence')
        second = client.get('/api/v1/timeline', params={'offset':10,'snapshot':first['snapshot']}).json()
        third = client.get('/api/v1/timeline', params={'offset':20,'snapshot':first['snapshot']}).json()
        ids = [r['id'] for page in [first,second,third] for r in page['items']]
        assert ids == initial_ids
        assert second['total'] == third['total'] == 25
        assert len(third['items']) == 5
        latest = client.get('/api/v1/timeline').json()
        assert latest['total'] == 26
        for params in [{'limit':0},{'offset':-1},{'snapshot':-1}]:
            assert client.get('/api/v1/timeline',params=params).status_code == 422

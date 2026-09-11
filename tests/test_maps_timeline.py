from fastapi.testclient import TestClient
from backend.app import create_app
from backend.models import MonitorCreate


def test_timeline_snapshot_pagination_stays_stable_during_polling(tmp_path):
    app = create_app(tmp_path / 'timeline.db', interval=0)
    with TestClient(app) as client:
        client.post('/api/v1/demo/seed')
        monitor = app.state.store.monitors()[0]
        for _ in range(21):
            app.state.store.poll(monitor['id'], 'sequence')
        first = client.get('/api/v1/timeline').json()
        assert len(first['items']) == 10 and first['total'] == 25
        initial_ids = [r['id'] for r in app.state.portal.timeline(limit=100)['items']]
        app.state.store.poll(monitor['id'], 'sequence')
        second = client.get('/api/v1/timeline', params={'offset':10,'snapshot':first['snapshot']}).json()
        third = client.get('/api/v1/timeline', params={'offset':20,'snapshot':first['snapshot']}).json()
        ids = [r['id'] for page in [first,second,third] for r in page['items']]
        assert ids == initial_ids
        assert second['total'] == third['total'] == 25
        assert len(third['items']) == 5
        latest = client.get('/api/v1/timeline').json()
        assert latest['total'] == 26
        assert len(client.get('/api/v1/dashboard').json()['timeline']) == 10
        for params in [{'limit':0},{'offset':-1},{'snapshot':-1}]:
            assert client.get('/api/v1/timeline',params=params).status_code == 422


def test_demo_flight_positions_and_absent_data(tmp_path):
    app = create_app(tmp_path / 'positions.db', interval=0)
    app.state.portal.seed()
    store = app.state.store
    flight = next(m for m in store.monitors() if m['kind']=='flight')
    initial = flight['latest']['data']
    assert initial['latitude'] is not None and initial['longitude'] is not None
    store.poll(flight['id'],'on_time')
    assert store.detail(flight['id'])['latest']['data']['longitude'] != initial['longitude']
    store.poll(flight['id'],'cancelled')
    assert store.detail(flight['id'])['latest']['data']['longitude'] is None
    store.poll(flight['id'],'missing')
    assert store.detail(flight['id'])['health'] == 'missing'
    unknown = store.create_monitor(MonitorCreate(kind='flight',name='Unknown route',carrier='RM',flight_number='200',service_date='2026-09-11',departure='AAA',arrival='BBB',scheduled_departure='2026-09-11T10:00:00Z',scheduled_arrival='2026-09-11T13:00:00Z'))
    store.poll(unknown['id'],'delayed')
    result=store.detail(unknown['id'])
    assert result['latest']['data']['longitude'] is None
    assert result['state']['exceeded'] is True

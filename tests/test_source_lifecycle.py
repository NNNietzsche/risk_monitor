import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.models import MonitorCreate, Observation
from backend.store import Store
from backend.provider_errors import FetchError


class PositionSource:
    name = 'test-position'

    def __init__(self, observed_at=None):
        self.observed_at = observed_at or datetime.now(timezone.utc)
        self.calls = 0

    def fetch(self, target, scenario, now):
        self.calls += 1
        return {'time': self.observed_at.isoformat(), 'mock': False}

    def normalize(self, payload, target):
        return Observation(kind=target['kind'], observed_at=payload['time'], longitude=47, latitude=12)


def register(store, source):
    store.registry.register(source, name='Test position source', kinds=['vessel','aircraft'],
                            capabilities={'vessel':['position'],'aircraft':['position']})


def test_only_current_live_sources_are_available_and_old_discovery_is_gone(tmp_path):
    app = create_app(tmp_path/'sources.db', interval=0)
    with TestClient(app) as client:
        sources = client.get('/api/v1/public/sources').json()
        assert {key for key, value in sources.items() if not value['is_mock']} == {
            'flightradar-sdk-v1', 'marinetraffic-sdk-v1'}
        assert client.get('/api/v1/public/targets').status_code == 404
        for old in ['digitraffic-v1','adsblol-v1']:
            response=client.post('/api/v1/monitors',json={
                'kind':'vessel','name':'Retired source','provider':old,'mmsi':'230991780','region_id':'demo-zone'})
            assert response.status_code == 422
        assert not client.get('/api/v1/monitors').json()


def test_real_position_evidence_immediate_refresh_and_duplicate_recovery(tmp_path):
    store=Store(tmp_path/'live.db');source=PositionSource();register(store,source)
    target=store.create_monitor(MonitorCreate(kind='vessel',name='Ship',mmsi='230991780',provider=source.name,region_id='demo-zone'))
    result=store.poll(target['id'])
    event=store.event_detail(result['events'][0])
    assert event['evidence']['is_mock'] is False
    assert event['raw_record']['provider']==source.name
    assert store.poll(target['id'])['outcome']=='duplicate' and source.calls==2
    with pytest.raises(ValueError): store.poll(target['id'],'inside')
    with store.connection() as db:
        db.execute("UPDATE monitors SET health='error',last_poll_at=NULL WHERE id=?",(target['id'],))
    assert store.poll(target['id'])['outcome']=='duplicate'
    assert store.detail(target['id'])['health']=='ok'
    assert len(store.events()['items'])==1


def test_stale_or_failed_position_never_creates_risk_event(tmp_path):
    store=Store(tmp_path/'stale.db');source=PositionSource(datetime.now(timezone.utc)-timedelta(hours=2));register(store,source)
    target=store.create_monitor(MonitorCreate(kind='vessel',name='Ship',mmsi='230991780',provider=source.name,region_id='demo-zone'))
    assert store.poll(target['id'])['outcome']=='stale'
    assert store.detail(target['id'])['latest'] is None and not store.events()['items']
    def fail(*args): raise FetchError('Unavailable',{'mock':False,'http_status':503})
    source.fetch=fail
    with store.connection() as db: db.execute('UPDATE monitors SET last_poll_at=NULL WHERE id=?',(target['id'],))
    assert store.poll(target['id'])['outcome']=='fetch_error'
    assert any(record['payload'].get('http_status')==503 for record in store.detail(target['id'])['raw_records'])
    assert not store.events()['items']


def test_existing_database_migration_retains_audit_and_events(tmp_path):
    path=tmp_path/'old.db'
    schema=Path('backend/schema.sql').read_text().replace("kind IN ('vessel','aircraft') AND asset_id", "kind='vessel' AND asset_id")
    with sqlite3.connect(path) as db: db.executescript(schema)
    with patch('backend.store.migrate_aircraft'):
        store=Store(path)
        target=store.create_monitor(MonitorCreate(kind='vessel',name='Existing',mmsi='999000001',region_id='demo-zone'))
        event_id=store.poll(target['id'],'inside')['events'][0]
    migrated=Store(path)
    assert migrated.event_detail(event_id)['monitor_id']==target['id']
    assert migrated.detail(target['id'])['configuration_audit']
    source=PositionSource();register(migrated,source)
    aircraft=migrated.create_monitor(MonitorCreate(kind='aircraft',name='Aircraft',provider=source.name,aircraft_registration='JA123A'))
    assert aircraft['kind']=='aircraft'
    with migrated.connection() as db: assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert Path(str(path)+'.before-aircraft.bak').exists()

import base64
import json
import sqlite3
from datetime import datetime,timezone,timedelta
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from backend.app import create_app
from backend.models import MonitorCreate
from backend.store import Store
from backend.live_providers import PublicHTTP, DigitrafficProvider, ADSBLolProvider, FetchError


def aircraft(store):
    return store.create_monitor(MonitorCreate(kind='aircraft',name='Test aircraft',provider='adsblol-v1',aircraft_registration='JA123A',icao24='abcdef'))


def ais(now,mmsi=230991780,longitude=47):
    return {'features':[{'geometry':{'type':'Point','coordinates':[longitude,12]},'properties':{'mmsi':mmsi,'timestampExternal':now.timestamp()*1000,'navStat':0}}]}


def adsb(now,**values):
    return {'now':now.timestamp()*1000,'ac':[{'hex':'abcdef','r':'JA123A','lat':35.5,'lon':139.7,'seen_pos':2,'flight':'TEST123','t':'B738',**values}]}


def test_live_vessel_event_preserves_source_response_and_throttles(tmp_path):
    store=Store(tmp_path/'live.db');now=datetime.now(timezone.utc);body=ais(now)
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.url.params['mmsi']=='230991780'
        return httpx.Response(200,json=body)
    store.providers['digitraffic-v1']=DigitrafficProvider(PublicHTTP(httpx.MockTransport(handler)))
    target=store.create_monitor(MonitorCreate(kind='vessel',name='Live ship',mmsi='230991780',provider='digitraffic-v1',region_id='demo-zone'))
    result=store.poll(target['id']);assert result['outcome']=='evaluated'
    event=store.event_detail(result['events'][0]);assert event['evidence']['is_mock'] is False
    raw=event['raw_record'];assert raw['provider']=='digitraffic-v1'
    assert json.loads(base64.b64decode(raw['payload']['response_bytes_base64']))==body
    assert store.poll(target['id'])['outcome']=='throttled' and len(calls)==1
    with pytest.raises(ValueError):store.poll(target['id'],'inside')


def test_aircraft_entity_has_position_but_no_flight_risk(tmp_path,monkeypatch):
    monkeypatch.setenv('PUBLIC_DATA_CONTACT','test@example.com')
    app=create_app(tmp_path/'aircraft.db',interval=0);store=app.state.store;now=datetime.now(timezone.utc)
    store.providers['adsblol-v1']=ADSBLolProvider(PublicHTTP(httpx.MockTransport(lambda r:httpx.Response(200,json=adsb(now)))))
    target=aircraft(store);assert target['flight'] is None
    assert store.poll(target['id'])['outcome']=='evaluated'
    target=store.detail(target['id']);assert target['state']['flight_risk_assessed'] is False
    assert datetime.fromisoformat(target['latest']['observed_at'])==now-timedelta(seconds=2)
    assert not store.events()['items']
    with TestClient(app) as client:
        row=client.get('/api/v1/timeline?kind=aircraft').json()['items'][0]
        assert row['provider']=='adsblol-v1' and row['assessment']['label']=='仅位置'
        assert client.get('/api/v1/health').json()['mode']=='live'
        assert client.get('/api/v1/dashboard').status_code==200
    assert app.state.portal.snapshot()['monitors'][0]['is_mock'] is False


@pytest.mark.parametrize('changes',[{'r':'DIFFERENT'},{'hex':'123456'},{'lat':None},{'seen_pos':-3}])
def test_aircraft_identity_and_position_validation(tmp_path,changes):
    store=Store(tmp_path/'bad.db');target=aircraft(store)
    with pytest.raises(ValueError):
        ADSBLolProvider(None).normalize({'body':adsb(datetime.now(timezone.utc),**changes)},target)


def test_missing_contact_and_http_error_are_audited_without_mock(tmp_path,monkeypatch):
    monkeypatch.delenv('PUBLIC_DATA_CONTACT',raising=False)
    store=Store(tmp_path/'errors.db');target=aircraft(store)
    assert store.poll(target['id'])['outcome']=='fetch_error'
    record=store.detail(target['id'])['raw_records'][0]
    assert record['payload']['mock'] is False and 'PUBLIC_DATA_CONTACT' in record['error']
    calls=[]
    def handler(request):
        calls.append(request);return httpx.Response(429,text='rate limited')
    transport=PublicHTTP(httpx.MockTransport(handler))
    for _ in range(2):
        with pytest.raises(FetchError) as exc:transport.get('https://meri.digitraffic.fi/api/ais/v1/locations')
        assert exc.value.payload['http_status']==429
    assert len(calls)==1


def test_stale_real_data_never_generates_event(tmp_path):
    store=Store(tmp_path/'stale.db')
    store.providers['digitraffic-v1']=DigitrafficProvider(PublicHTTP(httpx.MockTransport(lambda r:httpx.Response(200,json=ais(datetime.now(timezone.utc)-timedelta(hours=2))))))
    target=store.create_monitor(MonitorCreate(kind='vessel',name='Stale',provider='digitraffic-v1',mmsi='230991780',region_id='demo-zone'))
    assert store.poll(target['id'])['outcome']=='stale'
    assert store.detail(target['id'])['latest'] is None and not store.events()['items']


def test_existing_database_migration_retains_audit_and_events(tmp_path):
    path=tmp_path/'old.db'
    schema=Path('backend/schema.sql').read_text().replace("kind IN ('vessel','aircraft') AND asset_id", "kind='vessel' AND asset_id")
    with sqlite3.connect(path) as db:db.executescript(schema)
    # Populate the old structure without triggering the migration until after data exists.
    from unittest.mock import patch
    with patch('backend.store.migrate_aircraft'):
        store=Store(path)
        target=store.create_monitor(MonitorCreate(kind='vessel',name='Existing',mmsi='999000001',region_id='demo-zone'))
        event_id=store.poll(target['id'],'inside')['events'][0]
    migrated=Store(path)
    assert migrated.event_detail(event_id)['monitor_id']==target['id']
    assert migrated.detail(target['id'])['configuration_audit']
    assert aircraft(migrated)['kind']=='aircraft'
    with migrated.connection() as db:assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert Path(str(path)+'.before-aircraft.bak').exists()


def test_provider_capability_validation():
    with pytest.raises(ValidationError):MonitorCreate(kind='vessel',provider='digitraffic-v1',name='No MMSI',imo='9074729',region_id='demo-zone')
    with pytest.raises(ValidationError):MonitorCreate(kind='aircraft',provider='mock-v1',name='Wrong source',aircraft_registration='JA123A',icao24='abcdef')


def test_valid_duplicate_recovers_health_without_repeating_event(tmp_path):
    store=Store(tmp_path/'recovery.db');now=datetime.now(timezone.utc)
    store.providers['digitraffic-v1']=DigitrafficProvider(PublicHTTP(httpx.MockTransport(lambda r:httpx.Response(200,json=ais(now)))))
    target=store.create_monitor(MonitorCreate(kind='vessel',name='Recovery',provider='digitraffic-v1',mmsi='230991780',region_id='demo-zone'))
    assert store.poll(target['id'])['outcome']=='evaluated'
    with store.connection() as db:
        db.execute("UPDATE monitors SET health='error',last_error='transient',last_poll_at=NULL WHERE id=?",(target['id'],))
    assert store.poll(target['id'])['outcome']=='duplicate'
    assert store.detail(target['id'])['health']=='ok'
    assert len(store.events()['items'])==1

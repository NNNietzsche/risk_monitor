from copy import deepcopy
from datetime import datetime,timezone
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.models import MonitorCreate
from backend.sdk_providers import SDKGateway,MarineTrafficProvider,FlightRadarProvider
from backend.live_providers import FetchError


def test_sdk_backoff_cache_and_retry_after():
    clock=[0];g=SDKGateway(lambda:clock[0]);calls=[]
    def request():calls.append(1);return {'body':{}}
    g.run('source','a',request);g.run('source','a',request)
    assert len(calls)==1
    def fail():raise FetchError('rate limited',{'http_status':429,'retry_after':'3600'})
    with pytest.raises(FetchError):g.run('source','b',fail)
    clock[0]=1801
    with pytest.raises(FetchError):g.run('source','c',request)
    assert len(calls)==1
    clock[0]=3601;g.run('source','c',request);assert len(calls)==2


def test_marine_identity_position_and_age_are_not_invented(tmp_path):
    store=create_app(tmp_path/'mt.db',interval=0).state.store
    m=store.create_monitor(MonitorCreate(kind='vessel',name='Ship',imo='9795610',source_ref='5554510',provider='marinetraffic-sdk-v1',region_id='demo-zone'))
    now=int(datetime.now(timezone.utc).timestamp());body={'shipId':5554510,'timestamp':now,'lat':15,'lon':45,'areaName':'Test Sea'}
    provider=MarineTrafficProvider(SDKGateway(),lambda ref:{'body':deepcopy(body),'mock':False})
    store.providers[provider.name]=provider
    result=store.poll(m['id']);assert result['outcome']=='evaluated'
    event=store.event_detail(result['events'][0]);assert event['raw_record']['payload']['body']==body
    assert event['rule']['config']['source_ref']=='5554510'
    for bad in [{'shipId':5554511},{'lat':None},{'timestamp':None},{'imo':1234567}]:
        with pytest.raises(ValueError):provider.normalize({'body':body|bad},m)
    with pytest.raises(ValueError):store.create_monitor(MonitorCreate(kind='vessel',name='bad',mmsi='123456789',source_ref='0',provider=provider.name,region_id='demo-zone'))


def flight_body(now):
    return {'identification':{'id':'abcdef12','number':{'default':'NH8501'},'callsign':'ANA8501'},
      'airport':{'origin':{'code':{'iata':'NRT'}},'destination':{'code':{'iata':'DLC'}}},
      'aircraft':{'registration':'JA602F','model':{'code':'B763'}},
      'time':{'scheduled':{'departure':now-7200,'arrival':now+3600},'real':{'departure':now-3000},'estimated':{'arrival':now+5000},'other':{'updated':now}},
      'status':{'generic':{'status':{'text':'estimated'}}},'trail':[{'lat':35,'lng':130,'ts':now-10}]}


def make_flight(store,body):
    scheduled=body['time']['scheduled'];dep=datetime.fromtimestamp(scheduled['departure'],timezone.utc)
    return store.create_monitor(MonitorCreate(kind='flight',name='NH8501',provider='flightradar-sdk-v1',source_ref='abcdef12',
      carrier='NH',flight_number='8501',service_date=dep.date(),departure='NRT',arrival='DLC',
      aircraft_registration='JA602F',scheduled_departure=dep,scheduled_arrival=datetime.fromtimestamp(scheduled['arrival'],timezone.utc)))


def test_fr24_delay_uses_actual_time_and_keeps_raw(tmp_path):
    store=create_app(tmp_path/'fr.db',interval=0).state.store
    b=flight_body(int(datetime.now(timezone.utc).timestamp()));m=make_flight(store,b)
    provider=FlightRadarProvider(SDKGateway(),lambda kind,ref:{'body':deepcopy(b),'mock':False})
    store.providers[provider.name]=provider
    result=store.poll(m['id']);assert result['outcome']=='evaluated'
    detail=store.event_detail(result['events'][0]);assert detail['type']=='flight.delay_exceeded'
    assert detail['evidence']['delay_minutes']==70
    assert detail['raw_record']['payload']['body']==b
    assert detail['evidence']['current']['position_observed_at']
    for key,value in [('id','ffffffff'),('number',{'default':'NH8502'})]:
        bad=deepcopy(b);bad['identification'][key]=value
        with pytest.raises(ValueError):provider.normalize({'body':bad},m)
    bad=deepcopy(b);bad['time']['scheduled']['departure']+=86400
    with pytest.raises(ValueError):provider.normalize({'body':bad},m)
    bad=deepcopy(b);bad['aircraft']['registration']='JA123A'
    with pytest.raises(ValueError):provider.normalize({'body':bad},m)
    bad=deepcopy(b);bad['status']['generic']['status']['text']='canceled'
    assert provider.normalize({'body':bad},m).flight_status=='cancelled'


def test_fr24_aircraft_identity_route_and_no_implicit_flight(tmp_path):
    store=create_app(tmp_path/'ac.db',interval=0).state.store
    m=store.create_monitor(MonitorCreate(kind='aircraft',name='A',provider='flightradar-sdk-v1',aircraft_registration='JA602F',icao24='861b03'))
    now=int(datetime.now(timezone.utc).timestamp())
    row=['861B03',35,130,90,33000,450,'0',None,'B763','JA602F',now,'NRT','DLC','NH8501',0,0,'ANA8501',None,'ANA']
    provider=FlightRadarProvider(SDKGateway())
    obs=provider.normalize({'body':{'abc':row}},m)
    assert obs.kind=='aircraft' and obs.departure=='NRT' and obs.arrival=='DLC'
    assert obs.flight_status is None and obs.aircraft_role is None
    row[0]='ffffff'
    with pytest.raises(ValueError):provider.normalize({'body':{'abc':row}},m)
    with pytest.raises(ValueError):provider.normalize({'body':{}},m)


def test_sdk_catalog_source_reference_and_deployed_origin(tmp_path,monkeypatch):
    monkeypatch.setenv('RISK_ALLOWED_HOSTS','risk-monitor.bocom-tokyo.site')
    monkeypatch.setenv('RISK_ALLOWED_ORIGINS','https://risk-monitor.bocom-tokyo.site')
    with TestClient(create_app(tmp_path/'api.db',interval=0)) as c:
        sources=c.get('/api/v1/public/sources').json()
        assert sources['marinetraffic-sdk-v1']['reference_label']
        assert sources['flightradar-sdk-v1']['capabilities']['flight']==['position','flight_times','flight_status']
        assert c.post('/api/v1/poll?group=aviation',headers={'Origin':'https://risk-monitor.bocom-tokyo.site'}).status_code==200
        assert c.post('/api/v1/poll',headers={'Origin':'https://evil.example'}).status_code==403
        assert c.get('/api/v1/health',headers={'Host':'risk-monitor.bocom-tokyo.site'}).status_code==200
        assert c.get('/api/v1/health',headers={'Host':'evil.example'}).status_code==400

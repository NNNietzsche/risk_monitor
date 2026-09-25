from copy import deepcopy
from datetime import datetime,timezone
import pytest
from backend.app import create_app
from backend.models import MonitorCreate
from backend.sdk_providers import FlightRadarProvider,SDKGateway
from backend.convert_aircraft import convert
from tests.test_sdk_providers import flight_body,make_flight


def row(now,number='NH8501'):
    return ['861B03',35,130,90,33000,450,'0',None,'B763','JA602F',now,'NRT','DLC',number,0,0,'ANA'+number[2:],None,'ANA']


def target(store):
    return store.create_monitor(MonitorCreate(kind='aircraft',name='JA602F',provider='flightradar-sdk-v1',aircraft_registration='JA602F'))


def unlock(store,mid):
    with store.connection() as db:db.execute('UPDATE monitors SET last_poll_at=NULL WHERE id=?',(mid,))


def test_current_flight_rollover_keeps_registration_and_scopes_risk(tmp_path):
    store=create_app(tmp_path/'roll.db',interval=0).state.store;m=target(store)
    now=int(datetime.now(timezone.utc).timestamp())-20
    detail=flight_body(now);detail['aircraft']['model']['text']='Boeing 767-381F(ER)'
    detail['aircraft']['category']='Cargo'
    for idx,(fid,number) in enumerate([('abcdef12','NH8501'),('abcdef13','NH8502')]):
        tick=now+idx;detail['identification']['id']=fid;detail['identification']['number']['default']=number
        calls=[]
        def request(kind,ref):
            calls.append((kind,ref))
            return {'body':{fid:row(tick,number)} if kind=='registration' else deepcopy(detail)}
        store.providers[m['provider']]=FlightRadarProvider(SDKGateway(),request)
        unlock(store,m['id']);result=store.poll(m['id'])
        assert result['outcome']=='evaluated' and len(result['events'])==1
        current=store.detail(m['id'])
        assert current['asset']['registration']=='JA602F'
        assert current['latest']['data']['flight_number']==number
        assert current['business']['category_label']=='Cargo'
        assert current['business']['aircraft_model']=='Boeing 767-381F(ER)'
        assert calls==[('registration','JA602F'),('flight',fid)]
        assert store.event_detail(result['events'][0])['evidence']['flight_source_ref']==fid
    assert len(store.monitors())==1 and len(current['observations'])==2


def test_missing_feed_preserves_history_and_does_not_claim_grounded(tmp_path):
    store=create_app(tmp_path/'none.db',interval=0).state.store;m=target(store)
    now=int(datetime.now(timezone.utc).timestamp())
    p=FlightRadarProvider(SDKGateway(),lambda kind,ref:{'body':{'abcdef12':row(now)} if kind=='registration' else {}})
    store.providers[p.name]=p;store.poll(m['id']);before=store.detail(m['id'])['latest']
    store.providers[p.name]=FlightRadarProvider(SDKGateway(),lambda *args:{'body':{}})
    unlock(store,m['id']);assert store.poll(m['id'])['outcome']=='unavailable'
    current=store.detail(m['id']);assert current['latest']==before
    assert current['health']=='unavailable' and '不能据此确认' in current['last_error']


def test_wrong_detail_identity_or_missing_category_never_uses_manual_label(tmp_path):
    store=create_app(tmp_path/'identity.db',interval=0).state.store;m=target(store)
    m['profile']={'aircraft_role':'cargo'}
    now=int(datetime.now(timezone.utc).timestamp());detail=flight_body(now)
    detail['aircraft']['registration']='JA000A';detail['aircraft']['category']='Passenger'
    p=FlightRadarProvider(SDKGateway())
    obs=p.normalize({'body':{'abcdef12':row(now)},'current_flight_detail':{'body':detail}},m)
    assert obs.aircraft_category is None and obs.flight_status is None and obs.scheduled_departure is None
    from backend.business_profile import describe_profile
    m['latest']={'data':obs.model_dump(mode='json')}
    assert describe_profile(m)['category_label']=='分类未提供'


def test_optional_detail_failure_retains_position_and_error_evidence(tmp_path):
    store=create_app(tmp_path/'partial.db',interval=0).state.store;m=target(store)
    now=int(datetime.now(timezone.utc).timestamp())
    def request(kind,ref):
        if kind=='flight':raise ConnectionError('test')
        return {'body':{'abcdef12':row(now)}}
    store.providers[m['provider']]=FlightRadarProvider(SDKGateway(),request)
    assert store.poll(m['id'])['outcome']=='evaluated'
    detail=store.detail(m['id'])
    assert not detail['state']['flight_risk_assessed']
    assert detail['raw_records'][0]['payload']['current_flight_detail_error']


def test_explicit_conversion_keeps_ids_evidence_and_is_idempotent(tmp_path):
    store=create_app(tmp_path/'convert.db',interval=0).state.store
    body=flight_body(int(datetime.now(timezone.utc).timestamp()));m=make_flight(store,body)
    store.providers[m['provider']]=FlightRadarProvider(SDKGateway(),lambda *args:{'body':body})
    result=store.poll(m['id']);before=store.detail(m['id'])
    assert convert(store,['JA602F'])==[m['id']]
    after=store.detail(m['id'])
    assert after['kind']=='aircraft' and after['asset']['registration']=='JA602F'
    assert after['raw_records']==before['raw_records'] and after['observations']==before['observations']
    assert after['rule']['version']==before['rule']['version']+1
    assert store.event_detail(result['events'][0])['rule']['kind']=='flight'
    assert convert(store,['JA602F'])==[]
    with store.connection() as db:
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT id FROM flight_instances WHERE id=?',(m['flight']['id'],)).fetchone()

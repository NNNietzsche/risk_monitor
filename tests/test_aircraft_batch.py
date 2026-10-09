from copy import deepcopy
from datetime import datetime, timezone
import pytest
from backend.aircraft_batch import AircraftLiveFeed
from backend.app import create_app
from backend.collection import CollectionDeferred, RequestBudget
from backend.models import MonitorCreate
from backend.provider_errors import FetchError
from backend.sdk_providers import FlightRadarProvider, SDKGateway
from tests.test_aircraft_tracking import row
from tests.test_collection import Clock
from tests.test_sdk_providers import flight_body


def test_29_aircraft_share_one_feed_and_keep_independent_details_and_evidence(tmp_path):
    store=create_app(tmp_path/'batch.db',interval=0).state.store
    regs=[f'JA{i:03}A' for i in range(29)]
    targets=[store.create_monitor(MonitorCreate(kind='aircraft',name=reg,
        aircraft_registration=reg,provider='flightradar-sdk-v1')) for reg in regs]
    now=int(datetime.now(timezone.utc).timestamp())-20
    body={}
    for i,reg in enumerate(regs):
        sample=row(now); sample[9]=reg
        body[f'{0xabcdef12+i:x}']=sample
    original={'body':body,'http_status':200,'response_bytes_base64':'original-feed-bytes',
              'fetched_at':datetime.fromtimestamp(now,timezone.utc).isoformat()}
    calls=[]
    def request(kind,value):
        calls.append((kind,value))
        if kind=='registration': return deepcopy(original)
        reg=body[value][9]
        if kind=='category':
            return {'body':{'aircraftInfo':{'reg':reg,'service':1},'flightInfo':{'flightId':int(value,16)}}}
        detail=flight_body(now)
        detail['identification']['id']=value; detail['aircraft']['registration']=reg
        return {'body':detail}
    gateway=SDKGateway(); feed=AircraftLiveFeed(gateway,request)
    store.providers['flightradar-sdk-v1']=FlightRadarProvider(gateway,request,feed)
    batch_ids=set()
    for target in targets:
        assert store.poll(target['id'])['outcome']=='evaluated'
        detail=store.detail(target['id'])
        assert detail['latest']['data']['flight_source_ref'] in body
        assert body[detail['latest']['data']['flight_source_ref']][9]==target['name']
        payload=detail['raw_records'][0]['payload']
        assert payload['body']==original['body']
        assert payload['response_bytes_base64']==original['response_bytes_base64']
        assert payload['current_flight_detail']['body']['aircraft']['registration']==target['name']
        batch_ids.add(payload['live_batch']['id'])
    assert len(batch_ids)==1
    assert [v for k,v in calls if k=='registration']==[','.join(regs)]
    assert len([1 for k,v in calls if k=='flight'])==29
    assert len([1 for k,v in calls if k=='category'])==29
    # Archived or paused aircraft leave the next query, rather than remaining cached.
    store.set_enabled(targets[-1]['id'],False)
    store.poll(targets[0]['id'])
    assert [v for k,v in calls if k=='registration'][-1]==','.join(regs[:-1])


def test_snapshot_expiry_429_and_deferral_never_reuse_an_expired_response():
    clock=Clock(); calls=[]
    gateway=SDKGateway(RequestBudget(clock=clock,sleep=clock.sleep))
    def request(kind,value):
        calls.append(value)
        if len(calls)>1: raise FetchError('429',{'http_status':429,'retry_after':'0'})
        return {'body':{},'http_status':200}
    feed=AircraftLiveFeed(gateway,request,clock=clock)
    feed.configure(['JA602F','JA601F'])
    first=feed.fetch('JA601F')
    first['body']['mutated']=True
    assert feed.fetch('JA602F')['body']=={}
    clock.sleep(600)
    with pytest.raises(FetchError): feed.fetch('JA602F')
    with pytest.raises(CollectionDeferred): feed.fetch('JA601F')
    assert len(calls)==2


def test_large_watchlist_is_chunked_and_bad_responses_are_not_shared():
    calls=[]
    def request(kind,value): calls.append(value); return {'body':{}}
    regs=[f'JA{i:03}A' for i in range(51)]
    feed=AircraftLiveFeed(SDKGateway(),request)
    feed.configure(regs)
    for reg in regs: feed.fetch(reg)
    assert calls==[','.join(regs[:50]),regs[-1]]
    bad=AircraftLiveFeed(SDKGateway(),lambda *args:{'body':[]})
    with pytest.raises(FetchError): bad.fetch(regs[0])
    assert not bad.responses

from datetime import datetime,timezone
import json
import pytest
from backend.app import create_app
from backend.collection import RequestBudget,CollectionSchedule
from backend.enrollment import EnrollmentService,LookupUnavailable
from backend.models import Enrollment,MonitorCreate
from backend.provider_errors import FetchError
from backend.sdk_providers import SDKGateway,MarineTrafficProvider
from tests.test_collection import Clock,targets


def setup_transport(monkeypatch,clock,blocked=None):
    calls=[]
    class Response:
        def __init__(self,body,status=200):
            self.status_code=status;self.headers={'retry-after':'0'}
            self.body=body;self.content=json.dumps(body).encode()
        def json(self):return self.body
    class Session:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url,**kwargs):
            endpoint='info' if 'get_info_window' in url else url.rsplit('/',1)[-1]
            calls.append((endpoint,clock()))
            if endpoint==blocked:return Response({'error':'denied'},403)
            if endpoint=='search':return Response({'results':[{'id':5630138,'type':'IMO','value':9811000}]})
            if endpoint=='info':return Response({'values':{'ship_id':5630138}})
            return Response({'shipId':5630138,'imo':9811000,'name':'EVER GIVEN'})
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get_position(self,ref):
            calls.append(('position',clock()))
            return {'shipId':ref,'lat':12,'lon':47,'timestamp':int(datetime.now(timezone.utc).timestamp())}
    monkeypatch.setattr('backend.marine_details.Session',Session)
    monkeypatch.setattr('marinetraffic_api.MarineTrafficClient',Client)
    return calls


def gateway(clock):
    return SDKGateway(fr24_budget=RequestBudget(clock=clock,sleep=clock.sleep),
        marine_budget=RequestBudget(clock=clock,sleep=clock.sleep,backoff_statuses=('403','429')))


def test_identity_position_and_all_details_share_actual_http_spacing(tmp_path,monkeypatch):
    clock=Clock();g=gateway(clock);calls=setup_transport(monkeypatch,clock)
    store=create_app(tmp_path/'paced.db',interval=0).state.store
    store.providers['marinetraffic-sdk-v1']=MarineTrafficProvider(g)
    service=EnrollmentService(gateway=g)
    m=service.create(store,Enrollment(kind='vessel',identifier_type='imo',identifier='9811000'))
    assert m['health']=='ok' and m['latest']
    assert calls==list(zip(['search','general','position','general','voyage','info'],range(1000,1016,3)))


def test_optional_403_stops_followups_keeps_position_and_blocks_new_identity(tmp_path,monkeypatch):
    clock=Clock();g=gateway(clock);calls=setup_transport(monkeypatch,clock,blocked='general')
    store=create_app(tmp_path/'denied.db',interval=0).state.store
    store.providers['marinetraffic-sdk-v1']=MarineTrafficProvider(g)
    m=store.create_monitor(MonitorCreate(kind='vessel',name='Ship',source_ref='5630138',provider='marinetraffic-sdk-v1'))
    result=store.poll(m['id']);before=store.detail(m['id'])
    assert result['outcome']=='evaluated' and before['latest']
    assert calls==[('position',1000),('general',1003)]
    assert g.retry_in('marinetraffic-sdk-v1')==60
    payload=before['raw_records'][0]['payload']
    assert payload['details']['general_error']['http_status']==403
    assert 'voyage_error' not in payload['details'] and 'info_error' not in payload['details']
    assert store.poll(m['id'])['outcome']=='deferred'
    after=store.detail(m['id'])
    assert after['raw_records']==before['raw_records'] and after['last_poll_at']==before['last_poll_at']
    with pytest.raises(LookupUnavailable,match='60'):
        EnrollmentService(gateway=g).create(store,Enrollment(kind='vessel',identifier_type='imo',identifier='9811000'))
    assert len(calls)==2 and len(store.monitors())==1
    g.run('flightradar-sdk-v1','aircraft',lambda:{'body':{}})
    assert g.retry_in('marinetraffic-sdk-v1')==60


def test_sdk_retry_after_attribute_and_repeated_rejections_are_honored():
    from marinetraffic_api.errors import HTTPError
    clock=Clock();g=gateway(clock)
    def denied():raise HTTPError(403,'1800')
    with pytest.raises(FetchError) as error:g.run('marinetraffic-sdk-v1-position','ship',denied)
    assert error.value.payload['retry_after']=='1800' and g.retry_in('marinetraffic-sdk-v1')==1800
    clock.sleep(1800)
    def denied_without_hint():raise HTTPError(403,'0')
    with pytest.raises(FetchError):g.run('marinetraffic-sdk-v1-position','ship',denied_without_hint)
    assert g.retry_in('marinetraffic-sdk-v1')==120


def test_added_targets_change_future_spacing_but_keep_existing_reservation():
    schedule=CollectionSchedule(600);rows=targets()
    assert schedule.pick(rows,1000)=='flight0'
    reserved=schedule.next_slot['flight'];assert reserved==1000+600/29
    rows.append({'id':'new','provider':'flight','created_at':'999','last_poll_at':None})
    assert schedule.pick(rows,reserved-0.1) is None
    assert schedule.pick(rows,reserved)=='flight1'
    assert schedule.next_slot['flight']==reserved+600/30

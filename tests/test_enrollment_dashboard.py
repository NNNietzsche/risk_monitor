from copy import deepcopy
from datetime import datetime,timezone
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.enrollment import EnrollmentService
from backend.models import Enrollment,MonitorCreate
from backend.provider_errors import FetchError
from backend.sdk_providers import MarineTrafficProvider,SDKGateway


GENERAL={'shipId':5630138,'name':'EVER GIVEN','imo':9811000,'mmsi':636026627,'subtype':'Container Ship'}
PAYLOAD={'kind':'vessel','identifier_type':'imo','identifier':'9811000','remark':'项目甲'}


def setup(tmp_path,marine=None):
    def query(kind,value):
        if kind=='general':return {'body':deepcopy(GENERAL)}
        return {'body':{'results':[{'id':5630138,'type':'IMO' if value=='9811000' else 'MMSI','value':int(value)}]}}
    source=Mock(side_effect=marine or query)
    service=EnrollmentService(marine=source,aviation=Mock(side_effect=AssertionError('Unexpected external request')))
    app=create_app(tmp_path/'app.db',interval=0,enrollment=service)
    store=app.state.store
    provider=MarineTrafficProvider(SDKGateway(),lambda ref:{'body':{'shipId':ref,'timestamp':int(datetime.now(timezone.utc).timestamp()),'lat':12,'lon':47},'details':{'general':{'body':deepcopy(GENERAL)}}})
    store.providers[provider.name]=provider
    return app,source


@pytest.mark.parametrize('kind,value,requests',[('imo','9811000',2),('mmsi','636026627',2)])
def test_one_identifier_creates_source_named_target_and_optional_remark(tmp_path,kind,value,requests):
    app,source=setup(tmp_path)
    with TestClient(app) as c:
        r=c.post('/api/v1/monitors',json=PAYLOAD|{'identifier_type':kind,'identifier':value})
        assert r.status_code==201,r.text
        m=r.json();assert m['name']=='EVER GIVEN' and m['remark']=='项目甲'
        assert m['asset']['imo']=='9811000' and m['asset']['source_ref']=='5630138'
        assert {r['id'] for r in m['regions']}=={'hormuz','aden'}
        assert 'region_id' not in m['rule']['config']
        assert m['business']['category_label']=='Container Ship'
        assert m['latest'] and source.call_count==requests
        assert c.post('/api/v1/monitors',json=PAYLOAD).status_code==409
        updated=c.patch('/api/v1/monitors/'+m['id']+'/remark',json={'remark':'改名备注'}).json()
        assert updated['name']=='EVER GIVEN' and updated['remark']=='改名备注'
        assert 'identity_verified' in {r['action'] for r in updated['configuration_audit']}


@pytest.mark.parametrize('body',[
    PAYLOAD|{'identifier':'9811001'},PAYLOAD|{'identifier':'abcd'},
    PAYLOAD|{'identifier_type':'ship_id','identifier':'5630138'},
    PAYLOAD|{'identifier_type':'mmsi','identifier':'123'},
    PAYLOAD|{'provider':'mock-v1'},PAYLOAD|{'name':'manual'},PAYLOAD|{'region_id':'hormuz'}])
def test_invalid_form_does_not_lookup_or_create(tmp_path,body):
    app,source=setup(tmp_path)
    with TestClient(app) as c:
        assert c.post('/api/v1/monitors',json=body).status_code==422
        assert c.get('/api/v1/monitors').json()==[]
        assert source.call_count==0


@pytest.mark.parametrize('rows,label',[
    ([], '未找到'),
    ([{'id':1,'value':98110001,'type':'IMO'}],'未找到'),
    ([{'id':1,'value':9811000,'type':'MMSI'}],'未找到'),
    ([{'id':1,'value':9811000,'type':'IMO'},{'id':2,'value':9811000,'type':'IMO'}],'多艘')])
def test_no_fuzzy_or_ambiguous_identity_is_saved(tmp_path,rows,label):
    app,source=setup(tmp_path,lambda *args:{'body':{'results':rows}})
    with TestClient(app) as c:
        result=c.post('/api/v1/monitors',json=PAYLOAD)
        assert result.status_code==422 and label in result.json()['detail']
        assert not c.get('/api/v1/monitors').json()


def test_outage_and_identity_mismatch_leave_no_target(tmp_path):
    def fail(*args):raise FetchError('403',{'http_status':403})
    app,source=setup(tmp_path,fail)
    with TestClient(app) as c:
        result=c.post('/api/v1/monitors',json=PAYLOAD)
        assert result.status_code==503 and '暂时' in result.json()['detail']
        def mismatched(kind,value):
            if kind=='search':return {'body':{'results':[{'id':5630138,'type':'IMO','value':9811000}]}}
            return {'body':GENERAL|{'imo':9811001}}
        source.side_effect=mismatched
        result=c.post('/api/v1/monitors',json=PAYLOAD)
        assert result.status_code==422 and '不一致' in result.json()['detail']
        assert not c.get('/api/v1/monitors').json()


def test_core_dashboard_is_read_only_and_retired_routes_are_gone(tmp_path):
    app,source=setup(tmp_path)
    with TestClient(app) as c:
        m=c.post('/api/v1/monitors',json=PAYLOAD).json()
        calls=source.call_count;cursor=m['cursor']
        for _ in range(2):
            assert c.get('/api/v1/dashboard').status_code==200
            assert c.get('/api/v1/timeline').status_code==200
        assert c.get('/api/v1/monitors/'+m['id']).json()['cursor']==cursor
        assert calls==source.call_count
        assert c.post('/api/v1/monitors/'+m['id']+'/poll',json={'scenario':'inside'}).status_code==422
        assert c.get('/api/v1/monitors/'+m['id']).json()['cursor']==cursor
        assert set(c.get('/api/v1/public/sources').json())=={'marinetraffic-sdk-v1','flightradar-sdk-v1'}
        for method,path in [('POST','/demo/seed'),('GET','/news'),('POST','/news'),('GET','/ai/status'),('PATCH','/ai/settings'),('POST','/ai/refresh')]:
            assert c.request(method,'/api/v1'+path).status_code==404
        assert set(c.get('/api/v1/dashboard').json())=={'monitors','regions','events','updated_at'}
        for secret in ['/.env','/data/risk.db','/backend/schema.sql']:
            assert c.get(secret).status_code==404
        page=c.get('/').text
        assert '交通银行东京分行' in page and '船舶与航空资产风险监控' in page
        assert all(word not in page for word in ['载入演示','LIVE','刷新页面','AI 风险解释','公开风险信息'])
    with app.state.store.connection() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name IN ('public_news','ai_runs','ai_settings')").fetchall()


def test_delete_restore_and_global_region_changes_preserve_evidence(tmp_path):
    app,source=setup(tmp_path)
    with TestClient(app) as c:
        m=c.post('/api/v1/monitors',json=PAYLOAD).json();mid=m['id']
        event=c.get('/api/v1/events').json()['items'][0]
        original=c.get('/api/v1/events/'+event['id']).json()
        assert c.delete('/api/v1/regions/aden').status_code==200
        assert c.get('/api/v1/monitors/'+mid).json()['health']=='pending'
        assert c.delete('/api/v1/monitors/'+mid).status_code==200
        assert c.get('/api/v1/monitors').json()==[]
        assert c.post('/api/v1/monitors/'+mid+'/poll').status_code==409
        restored=c.post('/api/v1/monitors/'+mid+'/restore').json()
        assert not restored['enabled'] and not restored['deleted_at']
        assert c.get('/api/v1/events/'+event['id']).json()==original
        assert c.post('/api/v1/poll').json()['items']==[]
    reopened=create_app(app.state.store.path,interval=0)
    assert [r['id'] for r in reopened.state.store.regions()]==['hormuz']
    with reopened.state.store.connection() as db:assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_aircraft_identity_works_with_live_or_history_and_rejects_unknown():
    from tests.test_aircraft_tracking import row
    now=int(datetime.now(timezone.utc).timestamp())
    for live in [True,False]:
        def request(kind,value):
            return {'body':{'abcdef12':row(now)}} if kind=='registration' and live else {'body':{'result':{'response':{'data':[{'aircraft':{'registration':'JA602F'}}]}}}}
        service=EnrollmentService(aviation=request)
        m,evidence=service.resolve(Enrollment(kind='aircraft',identifier_type='registration',identifier='ja602f'))
        assert m.name==m.aircraft_registration=='JA602F'
    service=EnrollmentService(aviation=lambda *args:{'body':{}})
    with pytest.raises(ValueError,match='未查到'):
        service.resolve(Enrollment(kind='aircraft',identifier_type='registration',identifier='JA000X'))

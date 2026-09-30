from datetime import datetime,timezone
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.models import Observation


class NewVendor:
    name='independent-vendor'
    def fetch(self,target,scenario,now):
        return {'timestamp':now.isoformat(),'x':47,'y':12}
    def normalize(self,payload,target):
        return Observation(kind=target['kind'],observed_at=payload['timestamp'],longitude=payload['x'],latitude=payload['y'])


def test_new_provider_uses_unchanged_creation_rules_api_and_timeline(tmp_path):
    app=create_app(tmp_path/'new.db',interval=0)
    app.state.store.registry.register(NewVendor(),name='Independent source',kinds=['vessel'],
        capabilities={'vessel':['position']},required_fields={'vessel':['imo']})
    with TestClient(app) as c:
        catalog=c.get('/api/v1/public/sources').json()
        assert catalog['independent-vendor']['required_fields']=={'vessel':['imo']}
        m=c.post('/api/v1/monitors',json={'kind':'vessel','name':'New vendor vessel','provider':'independent-vendor','imo':'9074729','region_id':'demo-zone'}).json()
        assert m['source']['name']=='Independent source'
        assert 'min_poll_seconds' not in m['rule']['config']
        result=c.post('/api/v1/monitors/'+m['id']+'/poll',json={}).json()
        assert result['outcome']=='evaluated'
        event=c.get('/api/v1/events/'+result['events'][0]).json()
        assert event['type']=='vessel.first_seen_inside'
        assert event['evidence']['is_mock'] is False
        assert event['raw_record']['provider']=='independent-vendor'
        # Historical attribution comes from the immutable raw record, not current configuration.
        with app.state.store.connection() as db:db.execute("UPDATE monitors SET provider='mock-v1' WHERE id=?",(m['id'],))
        row=c.get('/api/v1/timeline').json()['items'][0]
        assert row['provider']=='independent-vendor' and row['source']['name']=='Independent source'


def test_unknown_provider_missing_identity_and_wrong_capabilities_are_rejected(tmp_path):
    app=create_app(tmp_path/'validation.db',interval=0)
    app.state.store.registry.register(NewVendor(),name='Position only',kinds=['flight'],capabilities={'flight':['position']})
    with TestClient(app) as c:
        vessel={'kind':'vessel','name':'X','imo':'9074729','region_id':'demo-zone'}
        assert c.post('/api/v1/monitors',json=vessel|{'provider':'unregistered'}).status_code==422
        assert c.post('/api/v1/monitors',json=vessel|{'provider':'marinetraffic-sdk-v1'}).status_code==422
        flight={'kind':'flight','name':'X','provider':'independent-vendor','carrier':'RM','flight_number':'123','service_date':'2026-09-11','departure':'HND','arrival':'PVG','scheduled_departure':'2026-09-11T10:00:00+09:00','scheduled_arrival':'2026-09-11T13:00:00+09:00'}
        assert c.post('/api/v1/monitors',json=flight).status_code==422
        assert not c.get('/api/v1/monitors').json()


def test_adapter_cannot_return_an_observation_of_another_asset_kind(tmp_path):
    app=create_app(tmp_path/'wrong-kind.db',interval=0)
    provider=NewVendor()
    provider.normalize=lambda payload,target:Observation(kind='aircraft',observed_at=payload['timestamp'],longitude=47,latitude=12)
    app.state.store.registry.register(provider,name='Broken adapter',kinds=['vessel'],capabilities={'vessel':['position']})
    with TestClient(app) as c:
        m=c.post('/api/v1/monitors',json={'kind':'vessel','name':'X','provider':provider.name,'imo':'9074729','region_id':'demo-zone'}).json()
        result=c.post('/api/v1/monitors/'+m['id']+'/poll',json={}).json()
        assert result['outcome']=='invalid' and not result['events']
        detail=c.get('/api/v1/monitors/'+m['id']).json()
        assert detail['raw_records'] and not detail['observations']

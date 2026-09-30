import asyncio
from datetime import datetime,timezone
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.models import MonitorCreate


def ship(c):
    r=c.post('/api/v1/monitors',json={'kind':'vessel','name':'业务测试船','mmsi':'999000009','region_id':'demo-zone','profile':{'vessel_type':'container'}})
    assert r.status_code==201
    return r.json()


def test_delete_restore_and_region_references_preserve_evidence(tmp_path):
    app=create_app(tmp_path/'management.db',interval=0)
    with TestClient(app) as c:
        m=ship(c);mid=m['id']
        event=c.post(f'/api/v1/monitors/{mid}/poll',json={'scenario':'inside'}).json()['events'][0]
        c.patch(f'/api/v1/monitors/{mid}',json={'enabled':False})
        assert c.delete('/api/v1/regions/demo-zone').status_code==409
        assert c.delete(f'/api/v1/monitors/{mid}').json()['deleted']
        assert c.get('/api/v1/monitors').json()==[]
        assert len(c.get('/api/v1/monitors?include_deleted=true').json())==1
        assert c.post(f'/api/v1/monitors/{mid}/poll',json={}).status_code==409
        assert c.patch(f'/api/v1/monitors/{mid}',json={'enabled':True}).status_code==409
        assert c.post('/api/v1/poll').json()['items']==[]
        assert c.get('/api/v1/events/'+event).json()['raw_record']['sha256']
        assert c.delete('/api/v1/regions/demo-zone').status_code==200
        assert c.get('/api/v1/regions').json()==[]
        assert c.post(f'/api/v1/monitors/{mid}/restore').status_code==409
        assert c.post('/api/v1/regions/demo-zone/restore').status_code==200
        restored=c.post(f'/api/v1/monitors/{mid}/restore').json()
        assert restored['deleted_at'] is None and not restored['enabled']
        assert restored['business']['category_label']=='集装箱船'
        assert {'created','deleted','restored'}.issubset({x['action'] for x in restored['configuration_audit']})
        assert c.delete('/api/v1/regions/no-such-region').status_code==404
    reopened=create_app(tmp_path/'management.db',interval=0)
    assert reopened.state.store.detail(mid)['raw_records']
    with reopened.state.store.connection() as db:assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_deleted_region_does_not_return_after_restart_and_profile_is_audited(tmp_path):
    path=tmp_path/'profile.db';app=create_app(path,interval=0)
    with TestClient(app) as c:
        m=ship(c);mid=m['id']
        updated=c.patch(f'/api/v1/monitors/{mid}/profile',json={'vessel_type':'tanker'}).json()
        assert updated['business']['category_label']=='油轮'
        assert updated['business']['category_source']=='manual'
        assert updated['configuration_audit'][0]['action']=='profile_changed'
        assert c.patch(f'/api/v1/monitors/{mid}/profile',json={'aircraft_role':'cargo'}).status_code==422
        c.delete(f'/api/v1/monitors/{mid}');c.delete('/api/v1/regions/demo-zone')
        assert c.patch(f'/api/v1/monitors/{mid}/profile',json={}).status_code==409
    assert create_app(path,interval=0).state.store.regions()==[]


def test_group_refresh_does_not_poll_other_group_or_paused_targets(tmp_path):
    app=create_app(tmp_path/'groups.db',interval=0)
    with TestClient(app) as c:
        c.post('/api/v1/demo/seed')
        ms=c.get('/api/v1/monitors').json();s=next(x for x in ms if x['kind']=='vessel');f=next(x for x in ms if x['kind']=='flight')
        rows=c.post('/api/v1/poll?group=vessel').json()['items'];assert [r['monitor_id'] for r in rows]==[s['id']]
        assert c.get('/api/v1/monitors/'+f['id']).json()['cursor']==f['cursor']
        rows=c.post('/api/v1/poll?group=aviation').json()['items'];assert [r['monitor_id'] for r in rows]==[f['id']]
        c.patch('/api/v1/monitors/'+s['id'],json={'enabled':False})
        assert c.post('/api/v1/poll?group=vessel').json()['items']==[]
        assert c.post('/api/v1/poll?group=invalid').status_code==422


def test_default_half_hour_scheduler_and_local_reads_do_not_fetch(tmp_path,monkeypatch):
    monkeypatch.delenv('RISK_POLL_SECONDS',raising=False)
    app=create_app(tmp_path/'hourly.db')
    calls=[]
    provider=app.state.store.providers['mock-v1']
    provider.fetch=lambda *args: calls.append(args)
    with TestClient(app) as c:
        ship(c)
        assert c.get('/api/v1/health').json()['scheduler_seconds']==600
        for _ in range(3):
            assert c.get('/api/v1/dashboard').status_code==200
            assert c.get('/api/v1/public/sources').status_code==200
        assert not calls


def test_aircraft_role_is_not_inferred_from_model_and_manual_edit_works(tmp_path):
    app=create_app(tmp_path/'aircraft-profile.db',interval=0)
    from backend.providers import MockProvider
    provider=MockProvider();provider.name='test-position'
    app.state.store.registry.register(provider,name='Test position source',kinds=['aircraft'],capabilities={'aircraft':['position']})
    with TestClient(app) as c:
        m=c.post('/api/v1/monitors',json={'kind':'aircraft','name':'A','provider':'test-position','aircraft_registration':'JA123A','icao24':'abcdef'}).json()
        assert m['business']['category_label']=='未分类'
        updated=c.patch('/api/v1/monitors/'+m['id']+'/profile',json={'aircraft_role':'cargo','aircraft_model':'B777F'}).json()
        assert updated['business']['category_label']=='货机' and updated['business']['aircraft_model']=='B777F'
        assert c.patch('/api/v1/monitors/'+m['id']+'/profile',json={'vessel_type':'container'}).status_code==422

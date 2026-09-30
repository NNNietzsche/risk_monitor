from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import pytest
from backend.models import MonitorCreate,RegionCreate
from backend.store import Store,encoded
from backend.management import change_region_deleted
from backend.regions import contains
from backend.sdk_providers import MarineTrafficProvider,SDKGateway


def setup(tmp_path):
    store=Store(tmp_path/'global.db')
    for region in store.regions():change_region_deleted(store,region['id'],True)
    a=store.create_region(RegionCreate(name='A',west=10,south=10,east=20,north=20))
    b=store.create_region(RegionCreate(name='B',west=15,south=15,east=25,north=25))
    tick=int(datetime.now(timezone.utc).timestamp())-30
    position={'shipId':5554510,'timestamp':tick,'lat':5,'lon':5}
    provider=MarineTrafficProvider(SDKGateway(),lambda ref:{'body':deepcopy(position)|{'shipId':ref}})
    store.providers[provider.name]=provider
    def ship(ref):return store.create_monitor(MonitorCreate(kind='vessel',name=ref,provider=provider.name,source_ref=ref))
    return store,a,b,position,ship


def test_every_ship_checks_every_region_and_overlapping_transitions_are_named(tmp_path):
    store,a,b,p,ship=setup(tmp_path);ships=[ship('5554510'),ship('5630138')]
    for m in ships:store.poll(m['id'])
    p.update(timestamp=p['timestamp']+1,lat=12,lon=12)
    for m in ships:
        event=store.event_detail(store.poll(m['id'])['events'][0])
        assert event['type']=='vessel.entered_region' and event['summary']=='船舶进入：A'
        assert {r['id'] for r in event['evidence']['regions']}=={a['id'],b['id']}
    p.update(timestamp=p['timestamp']+1,lat=18,lon=18)
    for m in ships:
        event=store.event_detail(store.poll(m['id'])['events'][0])
        assert event['summary']=='船舶进入：B'
        assert set(store.detail(m['id'])['state']['inside_regions'])=={'A','B'}
    p.update(timestamp=p['timestamp']+1,lat=23,lon=23)
    for m in ships:
        event=store.event_detail(store.poll(m['id'])['events'][0])
        assert event['summary']=='船舶离开：A'
        assert store.detail(m['id'])['state']['inside_regions']==['B']


def test_simultaneous_entries_and_exits_do_not_collide_or_repeat(tmp_path):
    store,a,b,p,ship=setup(tmp_path);m=ship('5554510');store.poll(m['id'])
    p.update(timestamp=p['timestamp']+1,lat=18,lon=18)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:store.poll(m['id']),range(2)))
    assert sum(len(r['events']) for r in results)==1
    event=store.events()['items'][0]
    assert set(event['evidence']['region_changes']['entered_region'])=={'A','B'}
    assert 'A' in event['summary'] and 'B' in event['summary']
    p.update(timestamp=p['timestamp']+1,lat=5,lon=5)
    assert len(store.poll(m['id'])['events'])==1
    assert not store.detail(m['id'])['state']['inside']


def test_polygon_edges_holes_and_defaults():
    polygon={'coordinates':[[[0,0],[4,0],[0,4],[0,0]],[[.5,.5],[1,.5],[1,1],[.5,1],[.5,.5]]]}
    assert contains(polygon,0,0) and contains(polygon,2,2)
    assert contains(polygon,.5,.5) and not contains(polygon,.7,.7)
    assert not contains(polygon,3,3)  # In bounding box, outside polygon.
    from backend.regions import defaults
    a,h={r['id']:r['geometry'] for r in defaults()}['aden'],{r['id']:r['geometry'] for r in defaults()}['hormuz']
    assert contains(a,47,12) and not contains(a,40,12)
    assert contains(h,56.5,26.5) and not contains(h,60,26)


def test_region_changes_reassess_same_fresh_position_preserve_original_evidence(tmp_path):
    store,a,b,p,ship=setup(tmp_path);m=ship('5554510');store.poll(m['id'])
    original=store.detail(m['id'])['latest']
    c=store.create_region(RegionCreate(name='C',west=0,south=0,east=8,north=8))
    assert store.detail(m['id'])['health']=='pending'
    event=store.event_detail(store.poll(m['id'])['events'][0])
    assert event['type']=='vessel.first_seen_inside' and event['summary'].endswith('C')
    assert event['evidence']['observation_id']==original['id']
    assert event['raw_record']['id']==original['raw_id']
    assert event['evidence']['policy_reassessment']
    assert len(store.detail(m['id'])['observations'])==1
    before=deepcopy(event)
    change_region_deleted(store,c['id'],True)
    result=store.poll(m['id'])
    assert not result['events'] and not store.detail(m['id'])['state']['inside']
    assert store.event_detail(event['id'])==before
    change_region_deleted(store,c['id'],False)
    assert store.poll(m['id'])['events']
    assert Store(store.path).detail(m['id'])['regions']


def test_stale_position_cannot_generate_new_region_alert(tmp_path):
    store,a,b,p,ship=setup(tmp_path);m=ship('5554510');store.poll(m['id'])
    store.create_region(RegionCreate(name='C',west=0,south=0,east=8,north=8))
    p['timestamp']-=7200
    assert store.poll(m['id'])['outcome']=='stale'
    assert store.events()['total']==0

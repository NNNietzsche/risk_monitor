from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
import pytest
from backend.collection import RequestBudget, CollectionDeferred, CollectionSchedule
from backend.sdk_providers import SDKGateway, FlightRadarProvider
from backend.provider_errors import FetchError
from backend.models import MonitorCreate, Enrollment
from backend.app import create_app
from backend.enrollment import EnrollmentService, LookupUnavailable


class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


def test_shared_budget_spacing_and_rate_limit_zero_no_requests_during_backoff():
    clock=Clock(); budget=RequestBudget(clock=clock, sleep=clock.sleep)
    gateway=SDKGateway(budget); calls=[]
    def ok(): calls.append(clock()); return {'body':{}}
    for source in ['flightradar-sdk-v1','flightradar-sdk-v1-category','flightradar-sdk-v1']:
        gateway.run(source,'x',ok)
    assert calls == [1000,1003,1006]
    def fail():
        calls.append(clock())
        raise FetchError('429',{'http_status':429,'retry_after':'0','response_bytes_base64':'evidence'})
    with pytest.raises(FetchError) as error: gateway.run('flightradar-sdk-v1','x',fail)
    assert error.value.payload['response_bytes_base64']=='evidence'
    assert budget.retry_in()==60
    for key in range(29):
        with pytest.raises(CollectionDeferred): gateway.run('flightradar-sdk-v1-category',key,ok)
    assert len(calls)==4
    gateway.run('marinetraffic-sdk-v1','ship',ok)  # independent source still works
    clock.sleep(60)
    with pytest.raises(FetchError): gateway.run('flightradar-sdk-v1','x',fail)
    assert budget.retry_in()==120
    clock.sleep(120); gateway.run('flightradar-sdk-v1','x',ok)
    assert budget.failures==0


@pytest.mark.parametrize('hint,minimum', [('3600',3600),('bad',60),('-1',60),('nan',60),('inf',60)])
def test_retry_after_numeric_or_invalid(hint,minimum):
    clock=Clock(); budget=RequestBudget(clock=clock,sleep=clock.sleep)
    def fail(): raise FetchError('429',{'http_status':429,'retry_after':hint})
    with pytest.raises(FetchError): budget.run(fail)
    assert budget.retry_in()==minimum


def test_retry_after_http_date_is_not_shortened():
    wall=datetime(2026,10,9,tzinfo=timezone.utc); clock=Clock()
    budget=RequestBudget(clock=clock,sleep=clock.sleep,wall_clock=lambda:wall)
    def fail(): raise FetchError('429',{'http_status':429,'retry_after':format_datetime(wall+timedelta(minutes=40))})
    with pytest.raises(FetchError): budget.run(fail)
    assert budget.retry_in()==2400


def targets(count=29, provider='flight'):
    return [{'id':provider+str(i),'provider':provider,'last_poll_at':None,'created_at':f'{i:03}'} for i in range(count)]


def test_29_targets_spread_fairly_over_two_cycles_with_no_starvation():
    schedule=CollectionSchedule(600); rows=targets(); selected=[]
    for now in range(1000,2230):
        chosen=schedule.pick(rows,now)
        if chosen:
            selected.append((now,chosen))
            next(m for m in rows if m['id']==chosen)['last_poll_at']=datetime.fromtimestamp(now,timezone.utc).isoformat()
    assert [v for _,v in selected[:29]] == [m['id'] for m in rows]
    assert [v for _,v in selected[29:58]] == [m['id'] for m in rows]
    assert selected[28][0]-selected[0][0]>=579
    assert all(b[0]-a[0]>=20 for a,b in zip(selected,selected[1:]))


def test_blocked_source_does_not_block_ships_or_consume_targets_and_no_catch_up_burst():
    schedule=CollectionSchedule(600); rows=targets()+targets(14,'ship')
    assert schedule.pick(rows,1000,{'flight':60})=='ship0'
    assert schedule.pick(rows,1001,{'flight':60}) is None
    assert schedule.pick(rows,1060)=='flight0'
    # Slow collection cannot accumulate missed slots and burst through the queue.
    # Both sources are due; tie order is irrelevant, each gets one slot.
    assert {schedule.pick(rows,1500),schedule.pick(rows,1501)}=={'ship1','flight1'}
    assert schedule.pick(rows,1502) is None


def test_rate_limit_after_selection_does_not_consume_a_target_cycle():
    schedule=CollectionSchedule(600); rows=targets()
    chosen=schedule.pick(rows,1000)
    schedule.defer(chosen)
    assert schedule.pick(rows,1001,{'flight':60}) is None
    assert schedule.pick(rows,1061)==chosen
    assert schedule.pick(rows,1062) is None


def test_restart_uses_persisted_last_poll_and_deleted_paused_targets_are_excluded(tmp_path):
    app=create_app(tmp_path/'schedule.db',interval=0); store=app.state.store
    m=store.create_monitor(MonitorCreate(kind='aircraft',name='JA602F',aircraft_registration='JA602F',provider='flightradar-sdk-v1'))
    assert len(store.collection_targets())==1
    now=datetime.now(timezone.utc)
    with store.connection() as db: db.execute('UPDATE monitors SET last_poll_at=? WHERE id=?',(now.isoformat(),m['id']))
    schedule=CollectionSchedule(600)
    assert schedule.pick(store.collection_targets(),now.timestamp()+599) is None
    assert schedule.pick(store.collection_targets(),now.timestamp()+600)==m['id']
    store.set_enabled(m['id'],False); assert not store.collection_targets()
    with store.connection() as db: db.execute('UPDATE monitors SET enabled=1,deleted_at=? WHERE id=?',(now.isoformat(),m['id']))
    assert not store.collection_targets()


def test_rate_limit_preserves_real_response_deferral_does_not_fabricate_raw_evidence(tmp_path):
    app=create_app(tmp_path/'rate.db',interval=0); store=app.state.store
    clock=Clock(); gateway=SDKGateway(RequestBudget(clock=clock,sleep=clock.sleep)); calls=[]
    def fail(*args):
        calls.append(args)
        raise FetchError('rate limited',{'http_status':429,'retry_after':'60','response_bytes_base64':'original'})
    store.providers['flightradar-sdk-v1']=FlightRadarProvider(gateway,fail)
    m=store.create_monitor(MonitorCreate(kind='aircraft',name='JA602F',aircraft_registration='JA602F',provider='flightradar-sdk-v1'))
    assert store.poll(m['id'])['outcome']=='fetch_error'
    before=store.detail(m['id'])
    assert before['health']=='rate_limited'
    assert store.poll(m['id'])['outcome']=='deferred'
    after=store.detail(m['id'])
    assert after['raw_records']==before['raw_records'] and after['last_poll_at']==before['last_poll_at']
    assert not after['evaluations'] and len(calls)==1
    # Enrollment honors the very same budget before attempting identity lookup.
    enrollment=EnrollmentService(aviation=fail,gateway=gateway)
    with pytest.raises(LookupUnavailable):
        enrollment.create(store,Enrollment(kind='aircraft',identifier_type='registration',identifier='JA602F'))
    assert len(calls)==1 and len(store.monitors())==1


def test_app_enrollment_and_collection_share_budget(tmp_path):
    app=create_app(tmp_path/'shared.db',interval=0)
    assert app.state.enrollment.gateway is app.state.store.providers['flightradar-sdk-v1'].gateway

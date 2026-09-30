"""Test-only deterministic source; never registered by the application."""
from backend.store import Store as RealStore, encoded, stamp
from backend.models import MonitorCreate
from tests.recorded_provider import MockProvider

def prepare(store):
    if 'recorded-v1' not in store.providers:
        store.registry.register(MockProvider(),name='Recorded fixture',kinds=['vessel','flight'],is_mock=True,
            capabilities={'vessel':['position'],'flight':['position','flight_times','flight_status']})
    with store.connection() as db:
        if not db.execute("SELECT 1 FROM regions WHERE id='test-zone'").fetchone():
            db.execute("UPDATE regions SET deleted_at=?",(stamp(),))
            db.execute('INSERT INTO regions(id,name,version,geometry,created_at) VALUES(?,?,?,?,?)',
                ('test-zone','Test boundary',1,encoded({'type':'Polygon','coordinates':[[[40,10],[50,10],[50,20],[40,20],[40,10]]],'bbox':[40,10,50,20]}),stamp()))
    return store

def create_store(path):return prepare(RealStore(path))
def monitor_request(**values):return MonitorCreate(**({'provider':'recorded-v1'}|values))
def sample(store,mid,scenario='sequence'):
    store.providers[store.detail(mid)['provider']].scenario=scenario
    return store.poll(mid)
def seed(store):
    prepare(store)
    vessel=store.create_monitor(monitor_request(kind='vessel',name='Test ship',mmsi='999000001'))
    flight=store.create_monitor(monitor_request(kind='flight',name='Test flight',carrier='RM',flight_number='101',service_date='2026-09-09',departure='HND',arrival='PVG',scheduled_departure='2026-09-09T10:00:00+09:00',scheduled_arrival='2026-09-09T13:00:00+09:00'))
    for target,a,b in [(vessel,'outside','inside'),(flight,'on_time','delayed')]:
        sample(store,target['id'],a);sample(store,target['id'],b)
    return vessel,flight

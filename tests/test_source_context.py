"""Recorded 2026-09-30 public responses; time shifts exercise lifecycle boundaries."""
import json
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pytest
from backend.store import Store
from backend.models import MonitorCreate
from backend.sdk_providers import SDKGateway, MarineTrafficProvider, FlightRadarProvider, NoLivePosition, flight_values
from tests.test_aircraft_tracking import row


def fixture(name):return json.loads((Path(__file__).parent/'fixtures'/name).read_text())


def ship(store):
    return store.create_monitor(MonitorCreate(kind='vessel',name='COSCO SHIPPING UNIVERSE',imo='9795610',mmsi='477157400',source_ref='5554510',provider='marinetraffic-sdk-v1'))


def test_satellite_context_and_voyage_survive_stale_position_without_new_risk(tmp_path):
    store=Store(tmp_path/'ship.db');m=ship(store);p=fixture('marine-context.json')
    p['body']['timestamp']=int(datetime.now(timezone.utc).timestamp())-7200
    provider=MarineTrafficProvider(SDKGateway(),lambda ref:deepcopy(p));store.providers[provider.name]=provider
    assert store.poll(m['id'])['outcome']=='stale'
    d=store.detail(m['id']);c=d['current']['data']
    assert d['current']['fresh'] and c['has_newer_satellite_position'] is True
    assert (c['departure_port'],c['arrival_port'])==('SINGAPORE','ROTTERDAM')
    assert d['business']['category_label']=='Container Ship'
    assert d['latest'] is None and not store.events()['items']
    assert d['raw_records'][0]['payload']==p
    # Fresh coastal data resumes evaluation without losing the satellite evidence.
    p['body'].update(timestamp=int(datetime.now(timezone.utc).timestamp()),hasNewerSatellitePosition=False)
    assert store.poll(m['id'])['outcome']=='evaluated'
    assert store.detail(m['id'])['current']['data']['has_newer_satellite_position'] is False


def test_metadata_identity_and_port_join_never_borrow_other_ship_or_old_voyage(tmp_path):
    store=Store(tmp_path/'identity.db');m=ship(store);p=fixture('marine-context.json');provider=MarineTrafficProvider(SDKGateway())
    p['details']['general']['body']['imo']=1234567
    p['details']['info']['body']['values']['next_port_id']='123'
    d=provider.normalize(p,m)
    assert d.vessel_type is None and d.arrival_port is None and d.departure_port=='SINGAPORE'
    p['details']['info']['body']['values']['ship_id']='777'
    assert provider.normalize(p,m).departure_port is None


def test_fetch_failure_invalidates_special_explanation_but_keeps_evidence(tmp_path):
    store=Store(tmp_path/'fail.db');m=ship(store);p=fixture('marine-context.json')
    store.providers[m['provider']]=MarineTrafficProvider(SDKGateway(),lambda ref:p)
    store.poll(m['id']);before=store.detail(m['id'])['current']
    def fail(ref):raise ConnectionError('offline')
    store.providers[m['provider']]=MarineTrafficProvider(SDKGateway(),fail)
    assert store.poll(m['id'])['outcome']=='fetch_error'
    after=store.detail(m['id'])['current']
    assert not after['fresh'] and after['raw_id']==before['raw_id']


def aircraft(store):
    return store.create_monitor(MonitorCreate(kind='aircraft',name='JA602F',aircraft_registration='JA602F',icao24='861b03',provider='flightradar-sdk-v1'))


def history_payload():
    b=fixture('fr-history.json');r=b['result']['response'];now=int(datetime.now(timezone.utc).timestamp())
    delta=now-r['timestamp'];r['timestamp']=now
    for flight in r['data']:
        for key in ['scheduled','real','estimated','other']:
            for field in ['departure','arrival','updated','eta']:
                value=flight['time'].get(key,{}).get(field)
                if value:flight['time'][key][field]=value+delta
    return {'body':b},now


def request_history(history):
    return lambda kind,ref:history if kind=='history' else {'body':{}}


def test_landed_history_keeps_coordinates_historical_and_can_see_next_flight(tmp_path):
    store=Store(tmp_path/'aircraft.db');m=aircraft(store);history,now=history_payload()
    store.providers[m['provider']]=FlightRadarProvider(SDKGateway(),lambda kind,ref:{'body':{'abcdef12':row(now-20)}} if kind=='registration' else {'body':{}})
    store.poll(m['id']);before=store.detail(m['id'])['latest']
    history['body']['result']['response']['data']=history['body']['result']['response']['data'][1:]
    store.providers[m['provider']]=FlightRadarProvider(SDKGateway(),request_history(history))
    assert store.poll(m['id'])['outcome']=='unavailable'
    d=store.detail(m['id']);assert d['current']['fresh'] and d['current']['data']['flight_status']=='landed'
    assert d['current']['data']['latitude'] is None and d['latest']==before
    planned=deepcopy(history['body']['result']['response']['data'][0])
    planned['identification'].update(id=None,number={'default':'NH8442'})
    planned['status']={'generic':{'status':{'text':'scheduled','type':'departure'}}}
    planned['time']={'scheduled':{'departure':now+3600,'arrival':now+7200},'real':{},'other':{}}
    history['body']['result']['response']['data'].insert(0,planned)
    assert store.poll(m['id'])['outcome']=='unavailable'
    d=store.detail(m['id']);assert d['current']['data']['flight_status']=='scheduled'
    assert d['current']['data']['flight_number']=='NH8442' and d['latest']==before
    assert not store.events()['items']


@pytest.mark.parametrize('change',['identity','old_response','ambiguous','future_actual'])
def test_unverified_history_does_not_claim_landed(tmp_path,change):
    store=Store(tmp_path/(change+'.db'));m=aircraft(store);history,now=history_payload()
    response=history['body']['result']['response'];response['data']=response['data'][1:];b=response['data'][0]
    if change=='identity':b['aircraft']['registration']='JA000A'
    if change=='old_response':response['timestamp']=now-7200
    if change=='ambiguous':b['status']['ambiguous']=True
    if change=='future_actual':b['time']['real']['arrival']=now+3600
    store.providers[m['provider']]=FlightRadarProvider(SDKGateway(),request_history(history))
    assert store.poll(m['id'])['outcome']=='unavailable'
    assert store.detail(m['id'])['current'] is None


def test_arrival_estimate_without_takeoff_evidence_is_not_preflight():
    assert flight_values({'status':{'generic':{'status':{'text':'estimated','type':'arrival'}}}})['flight_status'] is None


def test_verified_history_supplies_times_without_a_redundant_detail_request(tmp_path):
    store=Store(tmp_path/'history-budget.db');m=aircraft(store);history,now=history_payload()
    history['body']['result']['response']['data']=history['body']['result']['response']['data'][1:]
    calls=[]
    def request(kind,ref):
        calls.append(kind)
        if kind=='flight':raise AssertionError('history already contains the required flight details')
        return history if kind=='history' else {'body':{}}
    store.providers[m['provider']]=FlightRadarProvider(SDKGateway(),request)
    assert store.poll(m['id'])['outcome']=='unavailable'
    assert calls==['registration','history','category']
    data=store.detail(m['id'])['current']['data']
    assert data['flight_status']=='landed' and data['actual_arrival'] and data['scheduled_departure']

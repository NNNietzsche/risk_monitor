from datetime import datetime,timezone
from copy import deepcopy
from backend.app import create_app
from backend.sdk_providers import FlightRadarProvider,SDKGateway
from tests.test_aircraft_tracking import row,target
from tests.test_sdk_providers import flight_body


def test_live_airport_names_are_only_joined_to_matching_route_and_identity(tmp_path):
    store=create_app(tmp_path/'names.db',interval=0).state.store;m=target(store)
    now=int(datetime.now(timezone.utc).timestamp());detail=flight_body(now)
    detail['airport']['origin']['name']='Tokyo Narita International Airport'
    detail['airport']['destination']['name']='Dalian Zhoushuizi International Airport'
    provider=FlightRadarProvider(SDKGateway())
    payload={'body':{'abcdef12':row(now)},'current_flight_detail':{'body':detail}}
    data=provider.normalize(payload,m)
    assert data.departure_name==detail['airport']['origin']['name']
    assert data.arrival_name==detail['airport']['destination']['name']
    detail['airport']['destination']['code']['iata']='XYZ'
    wrong=provider.normalize(payload,m)
    assert wrong.arrival_name is None and wrong.departure_name is None

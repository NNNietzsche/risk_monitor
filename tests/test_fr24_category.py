import struct
import pytest
from backend.fr24_category import decode_response, CATEGORIES
from backend.sdk_providers import FlightRadarProvider, SDKGateway
from tests.test_aircraft_tracking import row, target, unlock
from backend.app import create_app
from datetime import datetime, timezone


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result) + bytes([value])


def nested(tag, value):
    return varint(tag << 3 | 2) + varint(len(value)) + value


def response(service=b'\x40\x00', trailer=b'grpc-status:0\r\n'):
    aircraft = nested(2, b'JA602F') + service
    flight = b'\x08' + varint(int('abcdef12', 16))
    message = nested(1, aircraft) + nested(4, flight)
    return b'\x00' + struct.pack('>I', len(message)) + message + b'\x80' + struct.pack('>I', len(trailer)) + trailer


@pytest.mark.parametrize('code,label', [(0,'Passenger'),(1,'Cargo'),(11,'Non-categorized'),(100,None),(None,None)])
def test_category_presence_and_unknown_values(code,label):
    decoded = decode_response(response(b'' if code is None else b'\x40' + varint(code)))
    assert decoded['aircraftInfo'] == {'reg':'JA602F','service':code}
    assert decoded['category_label'] == label
    assert decoded['flightInfo']['flightId'] == int('abcdef12',16)


@pytest.mark.parametrize('data', [b'',b'\x00',response()[:-1],response(trailer=b'grpc-status:7\r\n'),response(b'\x40\x80'),response(b'\x00')])
def test_bad_or_restricted_response_is_not_a_category(data):
    with pytest.raises(ValueError):decode_response(data)


def test_identity_and_category_failure_do_not_block_position(tmp_path):
    store=create_app(tmp_path/'category.db',interval=0).state.store;m=target(store)
    now=int(datetime.now(timezone.utc).timestamp())-10
    calls=[]
    def request(kind,ref):
        calls.append(kind)
        if kind=='category':raise ConnectionError('metadata unavailable')
        return {'body':{'abcdef12':row(now)} if kind=='registration' else {}}
    gateway=SDKGateway();provider=FlightRadarProvider(gateway,request)
    store.providers[m['provider']]=provider
    assert store.poll(m['id'])['outcome']=='evaluated'
    d=store.detail(m['id'])
    assert d['latest']['data']['aircraft_category'] is None
    assert d['raw_records'][0]['payload']['aircraft_category_error']
    assert provider.name not in gateway.failures
    assert provider.name+'-category' in gateway.failures
    # A different registration/flight must never lend its category to this aircraft.
    for reg,fid,expected in [('JA602F','abcdef12','Passenger'),('JA000A','abcdef12',None),('JA602F','abcdef13',None)]:
        body={'aircraftInfo':{'reg':reg,'service':0},'flightInfo':{'flightId':int(fid,16)}}
        obs=provider.normalize({'body':{'abcdef12':row(now)},'aircraft_category_detail':{'body':body}},m)
        assert obs.aircraft_category==expected

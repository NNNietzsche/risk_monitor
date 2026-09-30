"""Guest FlightDetails metadata, matching FR24's AIRCRAFT CATEGORY field.

Only the required protobuf fields are decoded; unknown fields are skipped.
No downloaded vendor JavaScript or authentication tokens are needed at runtime.
"""
import base64
import struct
import uuid
from datetime import datetime, timezone
from .provider_errors import FetchError

URL = 'https://data-feed.flightradar24.com/fr24.feed.api.v1.Feed/FlightDetails'
MAPPING_VERSION = 'fr24-aircraft-service-20260925'
DEVICE_ID = 'web-' + uuid.uuid4().hex
CATEGORIES = {
    0: 'Passenger', 1: 'Cargo', 2: 'Military or government',
    3: 'Business jet', 4: 'General aviation', 5: 'Helicopter',
    6: 'Lighter-than-air', 7: 'Glider', 8: 'Drone',
    9: 'Ground vehicle', 10: 'Other', 11: 'Non-categorized',
}


def _varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise ValueError('Truncated protobuf varint')
        byte = data[pos]
        pos += 1
        if shift == 63 and byte > 1:
            raise ValueError('Oversized protobuf varint')
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, pos
    raise ValueError('Invalid protobuf varint')


def _fields(data):
    pos = 0
    result = {}
    while pos < len(data):
        tag, pos = _varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if not field:
            raise ValueError('Invalid protobuf field')
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire in (1, 2, 5):
            if wire == 2:
                length, pos = _varint(data, pos)
            else:
                length = 8 if wire == 1 else 4
            if pos + length > len(data):
                raise ValueError('Truncated protobuf field')
            value, pos = data[pos:pos + length], pos + length
        else:
            raise ValueError('Unsupported protobuf wire type')
        result[field] = (wire, value)
    return result


def _get(fields, number, wire):
    value = fields.get(number)
    if value is None:
        return None
    if value[0] != wire:
        raise ValueError('Unexpected protobuf field type')
    return value[1]


def decode_response(data, header_status=None):
    pos, message, status = 0, None, header_status
    while pos < len(data):
        if pos + 5 > len(data):
            raise ValueError('Truncated gRPC frame')
        flag, length = data[pos], int.from_bytes(data[pos + 1:pos + 5], 'big')
        pos += 5
        if pos + length > len(data):
            raise ValueError('Truncated gRPC message')
        frame, pos = data[pos:pos + length], pos + length
        if flag == 128:
            for line in frame.decode('ascii').splitlines():
                key, _, value = line.partition(':')
                if key.strip().lower() == 'grpc-status':
                    status = value.strip()
        elif flag == 0 and message is None:
            message = frame
        else:
            raise ValueError('Unexpected gRPC frame')
    if str(status) != '0' or message is None:
        raise ValueError('Unsuccessful gRPC response')
    fields = _fields(message)
    aircraft = _fields(_get(fields, 1, 2) or b'')
    flight = _fields(_get(fields, 4, 2) or b'')
    reg = _get(aircraft, 2, 2)
    service = _get(aircraft, 8, 0)  # Missing is None; explicit zero means Passenger.
    return {
        'aircraftInfo': {'reg': reg.decode('utf-8') if reg is not None else None,
                         'service': service},
        'flightInfo': {'flightId': _get(flight, 1, 0)},
        'category_label': CATEGORIES.get(service),
        'category_mapping_version': MAPPING_VERSION,
    }


def category_request(flight_id):
    from curl_cffi.requests import Session
    # restrictionMode=NOT_VISIBLE (guest); never request restricted metadata.
    request = b'\x0d' + struct.pack('<I', int(flight_id, 16)) + b'\x10\x00\x18\x01'
    wire = b'\x00' + struct.pack('>I', len(request)) + request
    payload = {'mock': False, 'url': URL, 'flight_id': flight_id,
               'restriction_mode': 'NOT_VISIBLE', 'category_mapping_version': MAPPING_VERSION,
               'request_bytes_base64': base64.b64encode(wire).decode('ascii')}
    with Session(impersonate='chrome136', retry=0, allow_redirects=False, trust_env=False) as session:
        with session.stream('POST', URL, data=wire, timeout=20, headers={
            'content-type': 'application/grpc-web+proto', 'x-grpc-web': '1',
            'fr24-platform': 'web-26.267.1417', 'fr24-device-id': DEVICE_ID,
            'origin': 'https://www.flightradar24.com', 'referer': 'https://www.flightradar24.com/',
        }) as response:
            body = bytearray()
            for chunk in response.iter_content():
                body.extend(chunk)
                if len(body) > 8_000_000:
                    raise FetchError('FR24 分类响应过大', payload)
            payload.update(http_status=response.status_code,
                           fetched_at=datetime.now(timezone.utc).isoformat(),
                           grpc_status=response.headers.get('grpc-status'),
                           retry_after=response.headers.get('retry-after'),
                           response_bytes_base64=base64.b64encode(body).decode('ascii'))
            if response.status_code != 200:
                raise FetchError('FR24 分类请求失败', payload)
            try:
                payload['body'] = decode_response(bytes(body), payload['grpc_status'])
            except ValueError as exc:
                raise FetchError(str(exc), payload) from None
    return payload

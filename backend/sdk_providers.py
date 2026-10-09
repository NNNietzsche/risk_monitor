"""SDK boundary: vendor calls and shapes end here; rules consume Observation only."""
import base64
import dataclasses
import re
from datetime import datetime, timezone
from .provider_errors import FetchError
from .collection import CollectionDeferred
from .models import Observation
from .fr24_category import category_request, CATEGORIES


class NoLivePosition(ValueError):
    """A successful registration lookup contained no current position."""


def flight_values(body):
    times=body.get('time') or {}
    real=times.get('real') or {}
    generic_status=((body.get('status') or {}).get('generic') or {}).get('status') or {}
    generic=generic_status.get('text','').lower()
    status={'canceled':'cancelled','cancelled':'cancelled','diverted':'diverted'}.get(generic)
    if status is None:
        if real.get('arrival') or generic=='landed':status='landed'
        elif real.get('departure'):status='active'
        elif generic=='scheduled' or (generic in {'estimated','delayed'} and generic_status.get('type')=='departure'):status='scheduled'
    if (body.get('status') or {}).get('ambiguous') is True:status=None
    values={'flight_status':status}
    for prefix,source in [('scheduled',times.get('scheduled') or {}),('actual',real),('estimated',times.get('estimated') or {})]:
        for side in ['departure','arrival']:
            if source.get(side):values[prefix+'_'+side]=epoch(source[side])
    return values


def epoch(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError('来源缺少有效时间戳')
    return datetime.fromtimestamp(value, timezone.utc)


class SDKGateway:
    """One attempt per call, optionally sharing the production FR24 budget."""
    def __init__(self, fr24_budget=None):
        self.fr24_budget = fr24_budget

    def retry_in(self, source):
        return self.fr24_budget.retry_in() if self.fr24_budget and source.startswith('flightradar-sdk-v1') else 0

    def run(self, source, key, callback):
        try:
            return self.fr24_budget.run(callback) if self.fr24_budget and source.startswith('flightradar-sdk-v1') else callback()
        except CollectionDeferred:
            raise
        except Exception as exc:
            payload=getattr(exc,'payload',{})
            code=getattr(exc,'status_code',None) or payload.get('http_status')
            message = '数据源限流，已暂停请求，稍后自动继续' if str(code)=='429' else 'SDK 数据源暂不可用'+(f'（HTTP {code}）' if code else '')
            raise FetchError(message,
                             {'mock':False,'source':source,'http_status':code,
                              'error_type':type(exc).__name__,**payload}) from None


def fr24_request(kind, value):
    if kind=='category':return category_request(value)
    # Use the SDK transport and entity parser, avoiding get_flights' hidden
    # empty-feed retries. A scoped session also guarantees resource cleanup.
    from FlightRadarAPI.request import APIRequest
    from FlightRadarAPI.core import Core
    from FlightRadarAPI.flight_tracker_config import FlightTrackerConfig
    from curl_cffi.requests import Session
    params=None
    if kind=='flight':url=Core.flight_data_url.format(value)
    elif kind=='history':
        url=Core.api_flightradar_base_url+'/flight/list.json'
        params={'query':value,'fetchBy':'reg','limit':10,'page':1,
                'timestamp':int(datetime.now(timezone.utc).timestamp())}
    else:
        url=Core.real_time_flight_tracker_data_url
        params=dataclasses.asdict(FlightTrackerConfig())
        params['reg' if kind=='registration' else 'bounds']=value
    with Session(impersonate='chrome136',retry=0,allow_redirects=False,trust_env=False) as session:
        response=APIRequest(url,session=session,params=params,headers=Core.json_headers,timeout=20,
                            allowed_error_codes=list(range(300,600)),max_response_bytes=8_000_000)
        raw=response.get_response_object()
        payload={'mock':False,'url':url,'query':params,'http_status':response.get_status_code(),
                 'fetched_at':datetime.now(timezone.utc).isoformat(),
                 'response_bytes_base64':base64.b64encode(raw.content).decode('ascii'),
                 'retry_after':raw.headers.get('retry-after')}
        if payload['http_status']!=200:raise FetchError('FR24 请求失败',payload)
        payload['body']=response.get_json_content()
        return payload


def mt_request(ship_id):
    from marinetraffic_api import MarineTrafficClient
    from .marine_details import fetch_details
    with MarineTrafficClient(timeout=20) as client:body=client.get_position(ship_id)
    return {'mock':False,'body':body,'fetched_at':datetime.now(timezone.utc).isoformat(),
            'details':fetch_details(ship_id),
            'source_id':str(ship_id),'evidence_format':'sdk_original_json',
            'note':'SDK 返回完整 JSON；当前 SDK 不暴露原始 HTTP 字节或响应头'}


class MarineTrafficProvider:
    name='marinetraffic-sdk-v1'
    def __init__(self,gateway,request=mt_request):self.gateway,self.request=gateway,request
    def validate_target(self,target):
        if not target.source_ref or not target.source_ref.isdigit() or not 0<int(target.source_ref)<2**63:
            raise ValueError('船舶来源编号必须为正整数 shipId')
    def fetch(self,target,now):
        ref=target['rule']['config']['source_ref']
        if not ref.isdigit() or not 0<int(ref)<2**63:raise ValueError('船舶来源编号必须为正整数 shipId')
        return self.gateway.run(self.name,ref,lambda:self.request(int(ref)))
    def normalize(self,payload,target):
        b=payload['body'];ref=target['rule']['config']['source_ref']
        if type(b.get('shipId')) is not int or str(b['shipId'])!=ref:raise ValueError('船舶来源身份不匹配')
        # Identity mapping is explicitly recorded at creation. Never treat shipId as IMO/MMSI.
        for key in ['imo','mmsi']:
            if b.get(key) and target['asset'].get(key) and str(b[key])!=target['asset'][key]:raise ValueError('船舶标识不匹配')
        if b.get('lat') is None or b.get('lon') is None:raise ValueError('船舶未返回坐标')
        status={'Underway using Engine':'under_way','At Anchor':'at_anchor','Moored':'moored'}.get(b.get('navigationalStatus'),'unknown')
        details=payload.get('details') or {}
        joined={}
        for name in ['general','voyage','info']:
            item=(details.get(name) or {}).get('body') or {}
            identity=(item.get('values') or {}).get('ship_id') if name=='info' else item.get('shipId')
            if str(identity)!=ref:continue
            ids=(item.get('values') or {}) if name=='info' else item
            if any(ids.get(k) and target['asset'].get(k) and str(ids[k])!=target['asset'][k] for k in ['imo','mmsi']):continue
            joined[name]=item
        general=joined.get('general',{});voyage=joined.get('voyage',{});info=joined.get('info',{}).get('values',{})
        values={'vessel_type':general.get('subtype'), 'vessel_flag':general.get('country'),
                'vessel_name':general.get('name') or general.get('aisName'),
                'vessel_length':general.get('length'),'vessel_width':general.get('width'),
                'callsign':general.get('callsign'),'reported_destination':voyage.get('reportedDestination')}
        # Port names and voyage dates are joined by port IDs, never by approximate geography.
        for side,prefix in [('departure','last'),('arrival','next')]:
            port_id=voyage.get(side+'PortId')
            if port_id and str(port_id)==str(info.get(prefix+'_port_id')):
                values[side+'_port']=info.get(prefix+'_port_name')
                values[side+'_port_code']=info.get(prefix+'_port_unlocode')
            label=voyage.get(side+'Label')
            if voyage.get(side+'Timestamp') and label in {'ATD','ATA','ETD','ETA'}:
                values[('actual_' if label.startswith('A') else 'estimated_')+side]=epoch(voyage[side+'Timestamp'])
        return Observation(kind='vessel',observed_at=epoch(b.get('timestamp')),latitude=b['lat'],longitude=b['lon'],
                           position_observed_at=epoch(b.get('timestamp')),
                           navigation_status=status,location_name=b.get('areaName'),
                           has_newer_satellite_position=b.get('hasNewerSatellitePosition') if type(b.get('hasNewerSatellitePosition')) is bool else None,
                           speed_knots=b.get('speed'),course_degrees=b.get('course'),draught_meters=b.get('draught'),**values)


class FlightRadarProvider:
    name='flightradar-sdk-v1'
    def __init__(self,gateway,request=fr24_request,live_feed=None):
        self.gateway,self.request,self.live_feed=gateway,request,live_feed
    def validate_target(self,target):
        if target.kind=='flight' and not re.fullmatch('[0-9a-f]{6,16}',target.source_ref or ''):
            raise ValueError('航班来源编号需要当天 FR24 flight ID（小写十六进制）')
    def fetch(self,target,now):
        kind='flight' if target['kind']=='flight' else 'registration'
        ref=target['rule']['config']['source_ref'] if kind=='flight' else target['asset']['registration']
        payload=(self.live_feed.fetch(ref) if kind=='registration' and self.live_feed
                 else self.gateway.run(self.name,(kind,ref),lambda:self.request(kind,ref)))
        if kind=='flight':return payload
        matches=self._matches(payload,target)
        payload=dict(payload)
        payload['lookup_at']=now.isoformat()
        selected=None
        if not matches:
            try:
                payload['aircraft_history']=self.gateway.run(self.name,('history',ref),lambda:self.request('history',ref))
            except (ValueError,ConnectionError,TimeoutError) as exc:
                payload['aircraft_history_error']=getattr(exc,'payload',{'error':str(exc)})
            selected=self._history_flight(payload,target)
            fid=(selected.get('identification') or {}).get('id') if selected else None
            if not fid:
                previous=(target.get('current') or target.get('latest') or {}).get('data') or {}
                fid=previous.get('flight_source_ref')
            payload['queried_flight_id']=fid
        elif len(matches)==1:
            fid=matches[0].id
        else:return payload
        if not fid or not re.fullmatch('[0-9a-f]{6,16}',fid):return payload
        if selected is None:
            try:
                detail=self.gateway.run(self.name,('flight',fid),lambda:self.request('flight',fid))
                payload['current_flight_detail']=detail
            except (ValueError,ConnectionError,TimeoutError) as exc:
                # Optional detail failure must not discard a valid primary position.
                payload['current_flight_detail_error']=getattr(exc,'payload',{'error':str(exc)})
        try:
            # Optional metadata failures must not discard a valid primary position.
            payload['aircraft_category_detail']=self.gateway.run(
                self.name+'-category',fid,lambda:self.request('category',fid))
        except (ValueError,ConnectionError,TimeoutError) as exc:
            payload['aircraft_category_error']=getattr(exc,'payload',{'error':str(exc)})
        return payload

    def _history_flight(self,payload,target):
        response=(((payload.get('aircraft_history') or {}).get('body') or {}).get('result') or {}).get('response') or {}
        rows=response.get('data') or []
        now=datetime.fromisoformat(payload['lookup_at']).timestamp() if payload.get('lookup_at') else datetime.now(timezone.utc).timestamp()
        # Reject cached history older than the normal source freshness window.
        if not isinstance(response.get('timestamp'),(int,float)) or not -60<=now-response['timestamp']<=3600:return None
        expected=target['rule']['config'].get('icao24')
        rows=[b for b in rows if isinstance(b,dict) and (b.get('aircraft') or {}).get('registration')==target['asset']['registration']
              and (not expected or str((b.get('aircraft') or {}).get('hex','')).lower()==expected)]
        def times(b,kind,key):return ((b.get('time') or {}).get(kind) or {}).get(key) or 0
        def status(b):return flight_values(b)['flight_status']
        recent=[b for b in rows if times(b,'real','departure')<=now+60 and times(b,'scheduled','departure')<=now+60]
        active=[b for b in recent if status(b)=='active' and now-times(b,'real','departure')<=86400]
        if active:return max(active,key=lambda b:times(b,'real','departure'))
        completed=[b for b in recent if status(b) in {'landed','cancelled','diverted'}]
        last=max(completed,key=lambda b:times(b,'scheduled','departure'),default=None)
        boundary=times(last,'real','arrival') or times(last,'scheduled','departure') if last else 0
        planned=[b for b in rows if status(b)=='scheduled' and not times(b,'real','departure')
                 and max(now-21600,boundary)<times(b,'scheduled','departure')<=now+86400]
        if planned:return min(planned,key=lambda b:times(b,'scheduled','departure'))
        return last

    def _without_position(self,payload,target):
        b=self._history_flight(payload,target)
        if b is None:
            detail=(payload.get('current_flight_detail') or {}).get('body') or {}
            if (detail.get('identification') or {}).get('id')==payload.get('queried_flight_id'):
                b=detail
        if not b or (b.get('aircraft') or {}).get('registration')!=target['asset']['registration']:
            raise NoLivePosition('当前未返回实时位置，也没有可核实的航班状态')
        expected=target['rule']['config'].get('icao24')
        if expected and str((b.get('aircraft') or {}).get('hex','')).lower()!=expected:
            raise NoLivePosition('航班记录的飞机身份尚未核实')
        values=flight_values(b)
        if not values['flight_status']:
            raise NoLivePosition('当前未返回实时位置，也没有可核实的航班状态')
        now=datetime.fromisoformat(payload['lookup_at'])
        if any(values.get(k) and values[k].timestamp()>now.timestamp()+60 for k in ['actual_departure','actual_arrival']):
            raise NoLivePosition('来源实际起降时间无效，暂不能确认航班状态')
        if values['flight_status']=='active' and (not values.get('actual_departure') or (now-values['actual_departure']).total_seconds()>86400):
            raise NoLivePosition('航班起飞记录过旧，暂不能确认仍在飞行')
        if values['flight_status']=='scheduled' and (not values.get('scheduled_departure') or not -21600<=(values['scheduled_departure']-now).total_seconds()<=86400):
            raise NoLivePosition('未提供近期待执行航班，暂不能确认未起飞状态')
        previous=(target.get('current') or target.get('latest') or {}).get('data') or {}
        if previous.get('scheduled_departure') and values.get('scheduled_departure') and values['scheduled_departure']<datetime.fromisoformat(previous['scheduled_departure']):
            raise NoLivePosition('来源返回较早航班，暂不能确认当前航班状态')
        identity=b.get('identification') or {};fid=identity.get('id')
        # Scheduled rows can have no flight ID yet; route/times remain source facts.
        model=((b.get('aircraft') or {}).get('model') or {}).get('text')
        airports=b.get('airport') or {}
        for side,source in [('departure','origin'),('arrival','destination')]:
            code=((airports.get(source) or {}).get('code') or {}).get('iata')
            values[side]=code if re.fullmatch('[A-Z]{3}',code or '') else None
            values[side+'_name']=(airports.get(source) or {}).get('name') if values[side] else None
        category=(payload.get('aircraft_category_detail') or {}).get('body') or {}
        if fid and (category.get('aircraftInfo') or {}).get('reg')==target['asset']['registration'] and (category.get('flightInfo') or {}).get('flightId')==int(fid,16):
            service=(category.get('aircraftInfo') or {}).get('service')
            values['aircraft_category']=CATEGORIES.get(service) if type(service) is int else None
        updated=((b.get('time') or {}).get('other') or {}).get('updated')
        observed=max([0,updated or 0,*[int(values[k].timestamp()) for k in ['actual_departure','actual_arrival'] if values.get(k)]])
        if not observed:
            observed=int(datetime.fromisoformat(payload['lookup_at']).timestamp())
        return Observation(kind='aircraft',observed_at=epoch(observed),flight_number=(identity.get('number') or {}).get('default'),
            flight_source_ref=fid,aircraft_type=model,callsign=identity.get('callsign'),
            flight_context='scheduled' if values['flight_status']=='scheduled' else 'recent',**values)

    def _matches(self,payload,target):
        from FlightRadarAPI.entities.flight import Flight
        matches=[]
        for fid,raw in payload['body'].items():
            if not isinstance(raw,list) or len(raw)<19:continue
            f=Flight(fid,raw)
            if f.registration==target['asset']['registration']:matches.append(f)
        return matches

    def normalize(self,payload,target):
        if target['kind']=='flight':return self._flight(payload,target)
        matches=self._matches(payload,target)
        if not matches:return self._without_position(payload,target)
        if len(matches)!=1:raise ValueError('该注册号当前无唯一有效飞机定位')
        f=matches[0]
        expected=target['rule']['config'].get('icao24')
        if expected and str(f.icao_24bit).lower()!=expected:raise ValueError('飞机 ICAO24 与注册号不一致')
        values={}
        model=f.aircraft_code or None
        detail=(payload.get('current_flight_detail') or {}).get('body') or {}
        identity=detail.get('identification') or {};aircraft=detail.get('aircraft') or {}
        # Join by BOTH live flight ID and aircraft registration. Never reuse yesterday's flight.
        if detail and identity.get('id')==f.id and aircraft.get('registration')==f.registration:
            model=(aircraft.get('model') or {}).get('text') or model
            detail_airports=detail.get('airport') or {}
            route_matches=all(((detail_airports.get(side) or {}).get('code') or {}).get('iata')==code
                              for side,code in [('origin',f.origin_airport_iata),('destination',f.destination_airport_iata)])
            if route_matches and (identity.get('number') or {}).get('default')==f.number:
                values.update(flight_values(detail))
                values.update(departure_name=(detail_airports.get('origin') or {}).get('name'),
                              arrival_name=(detail_airports.get('destination') or {}).get('name'))
        category=(payload.get('aircraft_category_detail') or {}).get('body') or {}
        info=category.get('aircraftInfo') or {};flight_info=category.get('flightInfo') or {}
        # This is the map website's field, not the legacy clickhandler aircraft object.
        if info.get('reg')==f.registration and flight_info.get('flightId')==int(f.id,16):
            service=info.get('service')
            values['aircraft_category']=CATEGORIES.get(service) if type(service) is int else None
        return Observation(kind='aircraft',observed_at=epoch(f.time),latitude=f.latitude,longitude=f.longitude,flight_context='live',
            position_observed_at=epoch(f.time),flight_number=f.number or None,flight_source_ref=f.id,
            callsign=f.callsign or None,aircraft_type=model,
            departure=f.origin_airport_iata if re.fullmatch('[A-Z]{3}',f.origin_airport_iata or '') else None,
            arrival=f.destination_airport_iata if re.fullmatch('[A-Z]{3}',f.destination_airport_iata or '') else None,
            navigation_status='on_ground' if f.on_ground else 'airborne',**values)
    def _flight(self,payload,target):
        b=payload['body'];flight=target['flight'];identity=b.get('identification') or {}
        if identity.get('id')!=target['rule']['config']['source_ref']:raise ValueError('航班来源编号不匹配')
        if (identity.get('number') or {}).get('default')!=flight['carrier']+flight['flight_number']:raise ValueError('航班号不匹配')
        airports=b.get('airport') or {};times=b.get('time') or {};scheduled=times.get('scheduled') or {}
        for field,side in [('departure','origin'),('arrival','destination')]:
            if ((airports.get(side) or {}).get('code') or {}).get('iata')!=flight[field]:raise ValueError('航班机场不匹配')
            if epoch(scheduled.get(field))!=datetime.fromisoformat(flight['scheduled_'+field]):raise ValueError('航班日期或计划时间已变化，需核对实例')
        aircraft=b.get('aircraft') or {}
        expected=target['rule']['config'].get('aircraft_registration')
        if expected and expected!=aircraft.get('registration'):raise ValueError('航班执飞机已变化，需核对关联实体')
        real=times.get('real') or {};estimated=times.get('estimated') or {}
        generic=(((b.get('status') or {}).get('generic') or {}).get('status') or {}).get('text','').lower()
        status={'canceled':'cancelled','cancelled':'cancelled','diverted':'diverted'}.get(generic)
        if status is None:
            if real.get('arrival'):status='landed'
            elif real.get('departure'):status='active'
            elif generic in {'scheduled','estimated','delayed'}:status='scheduled'
        trail=[p for p in b.get('trail',[]) if isinstance(p,dict) and isinstance(p.get('ts'),(int,float))]
        position=max(trail,key=lambda p:p['ts']) if trail else {}
        updated=(times.get('other') or {}).get('updated') or 0
        observed=epoch(max(updated,position.get('ts',0)))
        values={}
        for field in ['departure','arrival']:
            for prefix,source in [('actual',real),('estimated',estimated)]:
                if source.get(field):values[prefix+'_'+field]=epoch(source[field])
        return Observation(kind='flight',observed_at=observed,flight_status=status,
            latitude=position.get('lat'),longitude=position.get('lng'),
            position_observed_at=epoch(position['ts']) if position else None,
            aircraft_type=(aircraft.get('model') or {}).get('code'),callsign=identity.get('callsign'),**values)

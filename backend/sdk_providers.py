"""SDK boundary: vendor calls and shapes end here; rules consume Observation only."""
import base64
import dataclasses
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from .live_providers import FetchError
from .models import Observation


def epoch(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError('来源缺少有效时间戳')
    return datetime.fromtimestamp(value, timezone.utc)


class SDKGateway:
    """One call per key, shared cache and source-wide backoff; no immediate retry."""
    def __init__(self, clock=time.monotonic):
        self.clock=clock
        self.lock=threading.RLock()
        self.cache={}
        self.failures={}

    def run(self, source, key, callback, ttl=120):
        with self.lock:
            now=self.clock()
            failure=self.failures.get(source)
            if failure and now<failure[0]:
                raise FetchError('数据源冷却中，稍后再试', {'mock':False,'source':source,'cooldown':True})
            cached=self.cache.get((source,key))
            if cached and now-cached[0]<ttl:return cached[1]
            try:
                result=callback()
            except Exception as exc:
                payload=getattr(exc,'payload',{})
                code=getattr(exc,'status_code',None) or payload.get('http_status')
                retry=getattr(exc,'retry_after',None) or payload.get('retry_after')
                delay=1800
                if retry:
                    try:delay=max(delay,float(retry))
                    except (TypeError,ValueError):
                        try:delay=max(delay,(parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds())
                        except (TypeError,ValueError,OverflowError):pass
                self.failures[source]=(self.clock()+delay,True)
                raise FetchError('SDK 数据源暂不可用'+(f'（HTTP {code}）' if code else '')+'，已暂停本源请求',
                                 {'mock':False,'source':source,'http_status':code,'error_type':type(exc).__name__,
                                  'retry_after':retry,'retry_seconds':delay,**payload}) from None
            self.cache[(source,key)]=(self.clock(),result)
            return result


def fr24_request(kind, value):
    # Use the SDK transport and entity parser, avoiding get_flights' hidden
    # empty-feed retries. A scoped session also guarantees resource cleanup.
    from FlightRadarAPI.request import APIRequest
    from FlightRadarAPI.core import Core
    from FlightRadarAPI.flight_tracker_config import FlightTrackerConfig
    from curl_cffi.requests import Session
    params=None
    if kind=='flight':url=Core.flight_data_url.format(value)
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
    with MarineTrafficClient(timeout=20) as client:body=client.get_position(ship_id)
    return {'mock':False,'body':body,'fetched_at':datetime.now(timezone.utc).isoformat(),
            'source_id':str(ship_id),'evidence_format':'sdk_original_json',
            'note':'SDK 返回完整 JSON；当前 SDK 不暴露原始 HTTP 字节或响应头'}


class MarineTrafficProvider:
    name='marinetraffic-sdk-v1'
    def __init__(self,gateway,request=mt_request):self.gateway,self.request=gateway,request
    def validate_target(self,target):
        if not target.source_ref or not target.source_ref.isdigit() or not 0<int(target.source_ref)<2**63:
            raise ValueError('船舶来源编号必须为正整数 shipId')
    def fetch(self,target,scenario,now):
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
        return Observation(kind='vessel',observed_at=epoch(b.get('timestamp')),latitude=b['lat'],longitude=b['lon'],
                           navigation_status=status,location_name=b.get('areaName'))


class FlightRadarProvider:
    name='flightradar-sdk-v1'
    def __init__(self,gateway,request=fr24_request):self.gateway,self.request=gateway,request
    def validate_target(self,target):
        if target.kind=='flight' and not re.fullmatch('[0-9a-f]{6,16}',target.source_ref or ''):
            raise ValueError('航班来源编号需要当天 FR24 flight ID（小写十六进制）')
    def fetch(self,target,scenario,now):
        kind='flight' if target['kind']=='flight' else 'registration'
        ref=target['rule']['config']['source_ref'] if kind=='flight' else target['asset']['registration']
        return self.gateway.run(self.name,(kind,ref),lambda:self.request(kind,ref))
    def normalize(self,payload,target):
        if target['kind']=='flight':return self._flight(payload,target)
        from FlightRadarAPI.entities.flight import Flight
        matches=[]
        for fid,raw in payload['body'].items():
            if not isinstance(raw,list) or len(raw)<19:continue
            f=Flight(fid,raw)
            if f.registration==target['asset']['registration']:matches.append(f)
        if len(matches)!=1:raise ValueError('该注册号当前无唯一有效飞机定位')
        f=matches[0]
        expected=target['rule']['config'].get('icao24')
        if expected and str(f.icao_24bit).lower()!=expected:raise ValueError('飞机 ICAO24 与注册号不一致')
        return Observation(kind='aircraft',observed_at=epoch(f.time),latitude=f.latitude,longitude=f.longitude,
            callsign=f.callsign or None,aircraft_type=f.aircraft_code or None,
            departure=f.origin_airport_iata if re.fullmatch('[A-Z]{3}',f.origin_airport_iata or '') else None,
            arrival=f.destination_airport_iata if re.fullmatch('[A-Z]{3}',f.destination_airport_iata or '') else None,
            navigation_status='on_ground' if f.on_ground else 'airborne')
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

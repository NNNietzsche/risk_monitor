"""Resolve one user-supplied identifier before creating a monitor."""
import re
from .models import MonitorCreate
from .marine_details import fetch_public
from .sdk_providers import fr24_request, FlightRadarProvider, SDKGateway
from .provider_errors import FetchError


class LookupUnavailable(Exception):
    pass


class EnrollmentService:
    def __init__(self, marine=fetch_public, aviation=fr24_request):
        self.marine, self.aviation = marine, aviation

    def resolve(self, request):
        try:
            return self._vessel(request) if request.kind == 'vessel' else self._aircraft(request)
        except (FetchError, ConnectionError, TimeoutError) as exc:
            raise LookupUnavailable('数据源暂时无法查询，请稍后重试；本次未创建监控对象') from exc

    def _vessel(self, request):
        ship_id = request.identifier
        evidence = {}
        if request.identifier_type != 'ship_id':
            search = self.marine('search',request.identifier)
            evidence['search'] = search
            body = search.get('body') or {}
            if not isinstance(body.get('results'),list):
                raise LookupUnavailable('船舶查询返回格式异常，请稍后重试')
            candidates = {str(row['id']) for row in body['results'] if isinstance(row,dict)
                          and row.get('type') == request.identifier_type.upper()
                          and str(row.get('value')) == request.identifier
                          and re.fullmatch(r'[1-9][0-9]{0,17}',str(row.get('id','')))}
            if not candidates:
                raise ValueError('未找到与该标识码完全匹配的船舶，请核对号码或改用其他标识码')
            if len(candidates) != 1:
                raise ValueError('该标识码匹配到多艘船，请改用船舶页面中的 shipId')
            ship_id = next(iter(candidates))
        general = self.marine('general',ship_id)
        evidence['general'] = general
        body = general.get('body') or {}
        if str(body.get('shipId')) != ship_id:
            raise ValueError('未找到对应船舶，或来源返回的船舶身份不一致；请核对标识码')
        if request.identifier_type != 'ship_id' and str(body.get(request.identifier_type)) != request.identifier:
            raise ValueError('船舶资料与输入标识码不一致，请核对后使用 shipId')
        name = body.get('name') or body.get('aisName')
        if not isinstance(name,str) or not name.strip():
            raise ValueError('来源尚未提供可确认的船舶名称，请核对标识码或稍后重试')
        imo, mmsi = str(body.get('imo') or ''),str(body.get('mmsi') or '')
        values = dict(kind='vessel',name=name,remark=request.remark,provider='marinetraffic-sdk-v1',source_ref=ship_id,
                      imo=imo if re.fullmatch(r'[0-9]{7}',imo) else None,
                      mmsi=mmsi if re.fullmatch(r'[0-9]{9}',mmsi) else None)
        return MonitorCreate(**values), evidence

    def _aircraft(self, request):
        registration = request.identifier
        live = self.aviation('registration',registration)
        target = {'asset':{'registration':registration},'rule':{'config':{}}}
        matches = FlightRadarProvider(SDKGateway())._matches(live,target)
        if len(matches) > 1:
            raise ValueError('来源返回多个同注册号目标，暂无法确认飞机身份，请稍后重试')
        evidence = {'live':live}
        if not matches:
            history = self.aviation('history',registration)
            evidence['history'] = history
            rows = (((history.get('body') or {}).get('result') or {}).get('response') or {}).get('data') or []
            if not isinstance(rows,list) or not any((r.get('aircraft') or {}).get('registration') == registration for r in rows if isinstance(r,dict)):
                raise ValueError('未查到该注册号的实时或近期航班记录，请核对注册号；本次未创建')
        return MonitorCreate(kind='aircraft',name=registration,aircraft_registration=registration,
                             provider='flightradar-sdk-v1',remark=request.remark), evidence

    def create(self, store, request):
        resolved, evidence = self.resolve(request)
        monitor = store.create_monitor(resolved)
        with store.connection() as db:
            store._audit(db,monitor['id'],'identity_verified',{},
                         {'input':request.model_dump(),'resolved':resolved.model_dump(mode='json'),'source_evidence':evidence})
        # Identity is already confirmed. A position outage is a monitoring health
        # state, and must not turn a successful enrollment into a retry/duplicate.
        try:
            store.poll(monitor['id'])
        except Exception:
            import logging
            logging.exception('Initial collection failed after verified enrollment')
        return store.detail(monitor['id'])

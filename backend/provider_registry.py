"""One composition point for adapters, capabilities, policy and attribution.

Business rules and web assets must not branch on vendor identifiers.
"""
from copy import deepcopy


class ProviderRegistry:
    def __init__(self):
        self.providers = {}
        self.specs = {}

    def register(self, provider, *, name, kinds, capabilities, required_fields=None,
                 is_mock=False, url=None, license=None, coverage='',
                 min_poll_seconds=60, max_age_seconds=900, reference_label=None, profile_mode='manual_fallback'):
        if provider.name in self.providers:
            raise ValueError('重复的数据源注册')
        self.providers[provider.name] = provider
        self.specs[provider.name] = dict(name=name, kinds=list(kinds), capabilities=capabilities,
            required_fields=required_fields or {}, is_mock=is_mock, live=not is_mock,
            url=url, license=license, coverage=coverage,
            min_poll_seconds=min_poll_seconds, max_age_seconds=max_age_seconds, reference_label=reference_label, profile_mode=profile_mode)

    def catalog(self):
        return deepcopy(self.specs)

    def source(self, provider_id):
        return deepcopy(self.specs.get(provider_id, dict(name=provider_id, is_mock=None,
            live=None, kinds=[], capabilities={}, required_fields={}, url=None,
            license=None, coverage='来源当前未注册')))

    def validate(self, request):
        spec=self.specs.get(request.provider)
        if not spec:
            raise ValueError('数据源未注册')
        if request.kind not in spec['kinds']:
            raise ValueError(spec['name']+' 不支持该监控类型')
        for field in spec['required_fields'].get(request.kind, []):
            if getattr(request, field, None) is None:
                raise ValueError(spec['name']+' 需要字段 '+field)
        required={'vessel':{'position'}, 'aircraft':{'position'}, 'flight':{'flight_times','flight_status'}}[request.kind]
        if not required.issubset(spec['capabilities'].get(request.kind, [])):
            raise ValueError('数据源能力不足以支持当前监控规则')
        validate=getattr(self.providers[request.provider],'validate_target',None)
        if validate:validate(request)
        return deepcopy(spec)


def create_registry():
    from .providers import MockProvider
    registry=ProviderRegistry()
    registry.register(MockProvider(),name='模拟数据',kinds=['vessel','flight'],is_mock=True,
        capabilities={'vessel':['position'],'flight':['position','flight_times','flight_status']},
        coverage='用于验证规则；不代表真实资产状态',min_poll_seconds=0)
    from .sdk_providers import SDKGateway, MarineTrafficProvider, FlightRadarProvider
    gateway=SDKGateway()
    registry.register(MarineTrafficProvider(gateway),name='MarineTraffic API',kinds=['vessel'],
        capabilities={'vessel':['position']},required_fields={'vessel':['source_ref']},
        reference_label='船舶来源编号 shipId（非 IMO/MMSI）',
        url='https://www.marinetraffic.com/',coverage='船舶位置与航行状态',
        min_poll_seconds=300,max_age_seconds=3600)
    registry.register(FlightRadarProvider(gateway),name='Flightradar24（FlightRadarAPI）',kinds=['aircraft','flight'],
        capabilities={'aircraft':['position','current_flight'],'flight':['position','flight_times','flight_status']},
        required_fields={'aircraft':['aircraft_registration'],'flight':['source_ref']},
        reference_label='当天航班来源编号（FR24 flight ID）',
        url='https://github.com/JeanExtreme002/FlightRadarAPI',coverage='飞机位置、当前航班与起降时刻',
        min_poll_seconds=300,max_age_seconds=3600,profile_mode='provider')
    return registry

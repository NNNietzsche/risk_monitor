"""One composition point for adapters, capabilities, policy and attribution.

Business rules and web assets must not branch on vendor identifiers.
"""
from copy import deepcopy


class ProviderRegistry:
    def __init__(self):
        self.providers = {}
        self.specs = {}
        self.discoverers = {}

    def register(self, provider, *, name, kinds, capabilities, required_fields=None,
                 is_mock=False, url=None, license=None, coverage='',
                 min_poll_seconds=60, max_age_seconds=900, discover=None):
        if provider.name in self.providers:
            raise ValueError('重复的数据源注册')
        self.providers[provider.name] = provider
        self.specs[provider.name] = dict(name=name, kinds=list(kinds), capabilities=capabilities,
            required_fields=required_fields or {}, is_mock=is_mock, live=not is_mock,
            url=url, license=license, coverage=coverage,
            min_poll_seconds=min_poll_seconds, max_age_seconds=max_age_seconds)
        if discover:
            self.discoverers[provider.name] = discover

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
        return deepcopy(spec)

    def discover(self):
        items,errors=[],[]
        for provider_id, fetch in self.discoverers.items():
            try:
                result=fetch()
                items.extend(result['items'])
                errors.extend(result['errors'])
            except (ValueError,KeyError,TypeError):
                errors.append(self.specs[provider_id]['name']+' 暂时不可用')
        return {'items':items, 'errors':errors, 'sources':self.catalog()}


def create_registry(http):
    from .providers import MockProvider
    from .live_providers import DigitrafficProvider, ADSBLolProvider, discover_vessels, discover_aircraft
    registry=ProviderRegistry()
    registry.register(MockProvider(),name='模拟数据',kinds=['vessel','flight'],is_mock=True,
        capabilities={'vessel':['position'],'flight':['position','flight_times','flight_status']},
        coverage='用于验证规则；不代表真实资产状态',min_poll_seconds=0)
    registry.register(DigitrafficProvider(http),name='Digitraffic / Fintraffic',kinds=['vessel'],
        capabilities={'vessel':['position']},required_fields={'vessel':['mmsi']},
        url='https://www.digitraffic.fi/en/marine-traffic/',license='CC BY 4.0',
        coverage='主要覆盖芬兰周边水域',discover=lambda:discover_vessels(http))
    registry.register(ADSBLolProvider(http),name='ADSB.lol',kinds=['aircraft'],
        capabilities={'aircraft':['position']},required_fields={'aircraft':['icao24','aircraft_registration']},
        url='https://www.adsb.lol/docs/open-data/api/',license='ODbL 1.0',
        coverage='社区接收覆盖内的飞机位置；不提供完整航班时刻。候选列表取东京附近，按标识查询不限于东京',
        max_age_seconds=120,discover=lambda:discover_aircraft(http))
    return registry

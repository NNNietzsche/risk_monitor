"""Public vessel metadata endpoints exposed by the user's MarineTraffic SDK.

The pinned position SDK predates get_general/get_voyage/get_info. Keep these
additional calls at the adapter boundary, preserving every original response.
"""
import base64
from datetime import datetime, timezone
from curl_cffi.const import CurlHttpVersion
from curl_cffi.requests import Session
from .provider_errors import FetchError
from .collection import CollectionDeferred


def fetch_public(kind, value):
    """Only the two fixed public routes needed to confirm vessel identity."""
    if kind not in {'search','general'}:
        raise ValueError('不支持的船舶查询类型')
    url = ('https://www.marinetraffic.com/en/global_search/search' if kind=='search'
           else f'https://www.marinetraffic.com/en/vessels/{int(value)}/general')
    params = {'term':value} if kind=='search' else None
    with Session(impersonate='chrome150',trust_env=False,retry=0,allow_redirects=False) as session:
        try:
            response=session.get(url,params=params,timeout=20,http_version=CurlHttpVersion.V2_0,
                accept_encoding='gzip, br',headers={
                    'accept':'application/json, text/plain, */*',
                    'accept-language':'zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7',
                    'x-requested-with':'XMLHttpRequest',
                    'referer':('https://www.marinetraffic.com/en/ais/home/centerx:-12.0/centery:25.0/zoom:4'
                               if kind=='search' else f'https://www.marinetraffic.com/en/ais/details/ships/shipid:{int(value)}'),
                    'sec-fetch-dest':'empty','sec-fetch-mode':'cors','sec-fetch-site':'same-origin',
                    'cache-control':'no-cache','pragma':'no-cache','priority':'u=1, i'})
            payload={'url':url,'query':params,'http_status':response.status_code,
                     'retry_after':response.headers.get('retry-after'),
                     'fetched_at':datetime.now(timezone.utc).isoformat(),
                     'response_bytes_base64':base64.b64encode(response.content).decode('ascii')}
            if response.status_code==404:
                return {**payload,'body':{}}
            if response.status_code!=200:
                raise FetchError('船舶身份查询暂不可用',payload)
            body=response.json()
            if not isinstance(body,dict):
                raise FetchError('船舶身份查询格式异常',payload)
            return {**payload,'body':body}
        except FetchError:
            raise
        except Exception as exc:
            raise FetchError('船舶身份查询暂不可用',{'error_type':type(exc).__name__}) from None


def fetch_details(ship_id, gateway=None):
    results = {}
    with Session(impersonate='chrome150', trust_env=False, retry=0, allow_redirects=False) as session:
        for name in ['general', 'voyage', 'info']:
            url = ('https://www.marinetraffic.com/en/ais/get_info_window_json' if name == 'info'
                   else f'https://www.marinetraffic.com/en/vessels/{ship_id}/{name}')
            params = {'asset_type':'ship', 'id':str(ship_id)} if name == 'info' else None
            try:
                def query():
                    response = session.get(url, params=params, timeout=20,
                    http_version=CurlHttpVersion.V2_0, accept_encoding='gzip, br', headers={
                    'accept':'application/json, text/plain, */*',
                    'accept-language':'zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7',
                    'x-requested-with':'XMLHttpRequest',
                    'referer':('https://www.marinetraffic.com/en/ais/home/centerx:-12.0/centery:25.0/zoom:4'
                               if name=='info' else f'https://www.marinetraffic.com/en/ais/details/ships/shipid:{ship_id}'),
                    'sec-fetch-dest':'empty','sec-fetch-mode':'cors','sec-fetch-site':'same-origin',
                    'cache-control':'no-cache','pragma':'no-cache','priority':'u=1, i'})
                    payload = {'url':url, 'query':params, 'http_status':response.status_code,
                           'retry_after':response.headers.get('retry-after'),
                           'fetched_at':datetime.now(timezone.utc).isoformat(),
                           'response_bytes_base64':base64.b64encode(response.content).decode('ascii')}
                    if response.status_code != 200:
                        raise FetchError('船舶补充信息暂不可用', payload)
                    body = response.json()
                    if not isinstance(body, dict):
                        raise FetchError('船舶补充信息格式无效', payload)
                    identity = (body.get('values') or {}).get('ship_id') if name == 'info' else body.get('shipId')
                    if str(identity) != str(ship_id):
                        raise FetchError('船舶补充信息身份不匹配', payload)
                    payload['body'] = body
                    return payload
                results[name] = (gateway.run('marinetraffic-sdk-v1-'+name,ship_id,query)
                                 if gateway else query())
            except CollectionDeferred:
                break  # Keep the valid primary response; no fabricated detail.
            except Exception as exc:
                results[name + '_error'] = getattr(exc, 'payload', {'error':str(exc)})
    return results

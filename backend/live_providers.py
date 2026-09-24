"""Public, keyless position feeds. Fixed origins; no fallback to simulated data."""
import base64
import json
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import httpx
from .models import Observation
from .business_profile import ais_vessel_type



class FetchError(ValueError):
    def __init__(self, message, payload=None):
        super().__init__(message)
        self.payload = payload or {"mock":False,"error":message}


class PublicHTTP:
    def __init__(self, transport=None):
        self.transport = transport
        self.cache = {}
        self.failures = {}
        self.lock = threading.RLock()

    def get(self, url, ttl=45):
        with self.lock:
            failure = self.failures.get(url)
            if failure and time.monotonic() < failure[0]:
                raise failure[1]
            cached = self.cache.get(url)
            if cached and time.monotonic()-cached[0] < ttl:
                return cached[1]
            payload = {"mock":False,"url":url,"fetched_at":datetime.now(timezone.utc).isoformat()}
            try:
                headers={"User-Agent":"RiskMonitorPrototype/0.2", "Digitraffic-User":"risk-monitor-prototype"}
                if url.startswith("https://api.adsb.lol/"):
                    contact=os.getenv("PUBLIC_DATA_CONTACT","").strip()
                    if not contact or "\r" in contact or "\n" in contact:
                        raise FetchError("ADSB.lol 需要本地配置 PUBLIC_DATA_CONTACT 联系邮箱或项目联系页面",payload)
                    headers["User-Agent"] += " (contact: " + contact + ")"
                with httpx.Client(timeout=httpx.Timeout(20,connect=10),transport=self.transport,follow_redirects=False,
                                  headers=headers) as client:
                    with client.stream("GET", url) as response:
                        payload.update(http_status=response.status_code, response_headers={k:v for k,v in response.headers.items() if k in {"date","etag","last-modified","retry-after","content-type"}})
                        raw=bytearray()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw)>8_000_000:
                                raise FetchError("公开源响应超过大小上限",payload)
                        payload["response_bytes_base64"]=base64.b64encode(raw).decode("ascii")
                        if response.status_code!=200:
                            raise FetchError(f"公开数据源返回 HTTP {response.status_code}",payload)
                        payload["body"]=json.loads(raw)
            except FetchError as exc:
                delay=120
                retry=payload.get("response_headers",{}).get("retry-after","")
                if retry:
                    try:
                        delay=max(delay,float(retry))
                    except ValueError:
                        try:
                            delay=max(delay,(parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds())
                        except (ValueError,TypeError,OverflowError):
                            pass
                self.failures[url]=(time.monotonic()+delay,exc)
                raise
            except (httpx.HTTPError,ValueError) as exc:
                payload["error_type"]=type(exc).__name__
                failure=FetchError("公开数据源连接失败或响应不是有效 JSON",payload)
                self.failures[url]=(time.monotonic()+120,failure)
                raise failure from exc
            self.cache[url]=(time.monotonic(),payload)
            return payload


class DigitrafficProvider:
    name="digitraffic-v1"
    def __init__(self, http):
        self.http=http
    def fetch(self,target,scenario,now):
        mmsi=target["asset"]["mmsi"]
        payload=dict(self.http.get(f"https://meri.digitraffic.fi/api/ais/v1/locations?mmsi={mmsi}"))
        try:
            payload['vessel_metadata']=self.http.get(f"https://meri.digitraffic.fi/api/ais/v1/vessels/{mmsi}",ttl=86400)
        except FetchError as exc:
            payload['metadata_error']=exc.payload
        return payload
    def normalize(self,payload,target):
        features=payload["body"].get("features",[])
        matches=[f for f in features if str(f.get("properties",{}).get("mmsi"))==target["asset"]["mmsi"]]
        if not matches:
            raise ValueError("该 MMSI 当前无公开 AIS 位置，可能不在此数据源覆盖范围")
        feature=max(matches,key=lambda f:f["properties"].get("timestampExternal",0))
        p=feature["properties"]
        if feature.get("geometry",{}).get("type")!="Point":
            raise ValueError("AIS 响应缺少点坐标")
        lon,lat=feature["geometry"]["coordinates"][:2]
        nav={0:"under_way",1:"at_anchor",2:"not_under_command",3:"restricted_maneuverability",4:"constrained_by_draught",5:"moored",6:"aground",7:"fishing",8:"under_way_sailing"}.get(p.get("navStat"),"unknown")
        metadata=payload.get('vessel_metadata',{}).get('body',{})
        category=ais_vessel_type(metadata.get('shipType')) if str(metadata.get('mmsi'))==target['asset']['mmsi'] else None
        return Observation(kind="vessel",observed_at=datetime.fromtimestamp(p["timestampExternal"]/1000,timezone.utc),
                           longitude=lon,latitude=lat,navigation_status=nav,vessel_type=category)


class ADSBLolProvider:
    name="adsblol-v1"
    def __init__(self,http):
        self.http=http
    def fetch(self,target,scenario,now):
        return self.http.get("https://api.adsb.lol/v2/icao/"+target["rule"]["config"]["icao24"])
    def normalize(self,payload,target):
        body=payload["body"]
        candidates=[a for a in body.get("ac",[]) if a.get("hex","").lower()==target["rule"]["config"]["icao24"]]
        if len(candidates)!=1:
            raise ValueError("该飞机当前没有公开 ADS-B 数据，可能离开接收范围")
        a=candidates[0]
        if a.get("r","").strip().upper()!=target["asset"]["registration"]:
            raise ValueError("飞机注册号与所选实体不一致")
        if a.get("lat") is None or a.get("lon") is None or a.get("seen_pos") is None:
            raise ValueError("飞机响应没有有效定位")
        seconds=float(a["seen_pos"])
        if not 0<=seconds<86400:
            raise ValueError("无效的 ADS-B 定位年龄")
        observed=datetime.fromtimestamp(float(body["now"])/1000,timezone.utc)-timedelta(seconds=seconds)
        return Observation(kind="aircraft",observed_at=observed,latitude=a["lat"],longitude=a["lon"],
                           navigation_status="on_ground" if a.get("alt_baro")=="ground" else "airborne",
                           callsign=str(a.get("flight","")).strip()[:20] or None,aircraft_type=str(a.get("t","")).strip()[:20] or None)


def discover_vessels(http):
    items,errors=[],[]
    now=datetime.now(timezone.utc)
    try:
        payload=http.get("https://meri.digitraffic.fi/api/ais/v1/locations",ttl=120)
        features=sorted(payload["body"]["features"],key=lambda f:f.get("properties",{}).get("timestampExternal",0),reverse=True)
        for f in features:
            p=f.get("properties",{});mmsi=str(p.get("mmsi",""))
            coords=f.get("geometry",{}).get("coordinates",[])
            age=now.timestamp()-p.get("timestampExternal",0)/1000
            if not re.fullmatch(r"\d{9}",mmsi) or not 0<=age<600 or len(coords)<2:
                continue
            name="MMSI "+mmsi
            try:
                meta=http.get("https://meri.digitraffic.fi/api/ais/v1/vessels/"+mmsi,ttl=3600)["body"]
                name=str(meta.get("name") or name).strip()[:100]
            except (FetchError,AttributeError):
                pass
            items.append({"kind":"vessel","provider":"digitraffic-v1","name":name,"mmsi":mmsi,"longitude":coords[0],"latitude":coords[1],"observed_at":datetime.fromtimestamp(p["timestampExternal"]/1000,timezone.utc).isoformat()})
            if len(items)>=3:
                break
        if not items:
            errors.append("Digitraffic 暂无最近 10 分钟的船舶位置")
    except (FetchError,KeyError,TypeError,ValueError):
        errors.append("Digitraffic 暂时不可用")
    return {"items":items,"errors":errors}


def discover_aircraft(http):
    items,errors=[],[]
    now=datetime.now(timezone.utc)
    try:
        payload=http.get("https://api.adsb.lol/v2/lat/35.55/lon/139.78/dist/100",ttl=120)
        count=0
        planes=sorted(payload["body"].get("ac",[]),key=lambda a: not (a.get("flight","").strip() and a.get("t","").startswith(("A3","B7"))))
        for a in planes:
            reg=a.get("r","").strip().upper();hex_id=a.get("hex","").lower()
            age=now.timestamp()-payload["body"]["now"]/1000+a.get("seen_pos",999)
            if not re.fullmatch(r"[A-Z0-9-]{3,12}",reg) or not re.fullmatch(r"[0-9a-f]{6}",hex_id) or a.get("lat") is None or a.get("lon") is None or not 0<=age<=120:
                continue
            items.append({"kind":"aircraft","provider":"adsblol-v1","name":reg,"aircraft_registration":reg,"icao24":hex_id,"longitude":a["lon"],"latitude":a["lat"],"callsign":str(a.get("flight","")).strip(),"aircraft_type":a.get("t"),"observed_at":(datetime.fromtimestamp(payload["body"]["now"]/1000,timezone.utc)-timedelta(seconds=a["seen_pos"])).isoformat()})
            count+=1
            if count>=3:break
        if not count:errors.append("东京附近暂时没有可用飞机位置")
    except (FetchError,KeyError,TypeError,ValueError):
        errors.append("ADSB.lol 暂时不可用")
    return {"items":items,"errors":errors}

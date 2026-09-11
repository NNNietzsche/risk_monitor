"""Pure deterministic rules; no AI, I/O or clock reads."""
from datetime import datetime
ENGINE_VERSION = "1.0.0"


def evaluate(target, observation):
    previous, config = target["state"], target["rule"]["config"]
    evidence = {"current": observation, "previous_observation_id": (target.get("latest") or {}).get("id"),
                "previous_state": previous, "rule_config": config, "engine_version": ENGINE_VERSION,
                "operator": ">" if target["kind"] == "flight" else "boundary_inclusive",
                "data_source": target["provider"], "is_mock": target["source"]["is_mock"]}
    events = []
    if target["kind"] == "vessel":
        lat, lon = observation.get("latitude"), observation.get("longitude")
        if lat is None or lon is None:
            return None, "missing", evidence, events
        west, south, east, north = target["region"]["geometry"]["bbox"]
        inside = west <= lon <= east and south <= lat <= north
        evidence.update(region=target["region"], latitude=lat, longitude=lon, inside=inside)
        old = previous.get("inside")
        if inside and old is None:
            events.append(("vessel.first_seen_inside", "warning", "首次有效定位发现船舶位于风险区域"))
        elif inside and old is False:
            events.append(("vessel.entered_region", "high", "船舶由区域外变为区域内"))
        elif not inside and old is True:
            events.append(("vessel.exited_region", "info", "船舶已离开风险区域"))
        return {"inside": inside}, "evaluated", evidence, events

    if target["kind"] == "aircraft":
        evidence.update(operator="position_available", capabilities=["position"], flight_risk_assessed=False)
        if observation.get("latitude") is None or observation.get("longitude") is None:
            return None, "missing", evidence, events
        return {"position_available":True,"flight_risk_assessed":False}, "evaluated", evidence, events

    status, basis = observation.get("flight_status"), config["delay_basis"]
    actual, estimated = observation.get("actual_" + basis), observation.get("estimated_" + basis)
    chosen = actual or estimated
    if status in {"cancelled", "diverted"}:
        if previous.get("flight_status") != status:
            label = "取消" if status == "cancelled" else "备降"
            events.append(("flight." + status, "high", "航班状态变为" + label))
        return {**previous, "flight_status": status}, "evaluated", evidence, events
    if status is None or chosen is None:
        return None, "missing", evidence, events
    scheduled = target["flight"]["scheduled_" + basis]
    delay = (datetime.fromisoformat(chosen) - datetime.fromisoformat(scheduled)).total_seconds() / 60
    exceeded = delay > config["threshold_minutes"]
    evidence.update(delay_minutes=delay, scheduled_time=scheduled, compared_time=chosen,
                    time_basis=("actual_" if actual else "estimated_") + basis)
    if previous.get("flight_status") in {"cancelled", "diverted"}:
        events.append(("flight.status_restored", "info", "数据源报告航班已恢复常规状态"))
    if exceeded and previous.get("exceeded") is not True:
        events.append(("flight.delay_exceeded", "high", f"航班延误 {delay:g} 分钟，超过 {config['threshold_minutes']} 分钟阈值"))
    elif not exceeded and previous.get("exceeded") is True:
        events.append(("flight.delay_recovered", "info", "航班延误已回落到阈值以内"))
    return {"exceeded": exceeded, "delay_minutes": delay, "flight_status": status}, "evaluated", evidence, events

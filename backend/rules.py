"""Pure deterministic rules; no I/O or clock reads."""
from datetime import datetime
from .regions import contains, revision
ENGINE_VERSION = "1.2.0"


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
        regions = target['regions']
        states, changes = {}, {'first_seen_inside':[], 'entered_region':[], 'exited_region':[]}
        for region in regions:
            inside = contains(region['geometry'],lon,lat)
            old = previous.get('regions',{}).get(region['id'],{})
            before = old.get('inside') if old.get('version') == region['version'] else None
            states[region['id']] = {'inside':inside,'name':region['name'],'version':region['version']}
            if inside and before is None:
                changes['first_seen_inside'].append(region['name'])
            elif inside and before is False:
                changes['entered_region'].append(region['name'])
            elif not inside and before is True:
                changes['exited_region'].append(region['name'])
        for key,severity,label in [('first_seen_inside','warning','首次有效定位位于'),('entered_region','high','船舶进入'),('exited_region','info','船舶离开')]:
            if changes[key]:
                events.append(('vessel.'+key,severity,label+'：'+'、'.join(changes[key])))
        inside_names = [r['name'] for r in states.values() if r['inside']]
        state = {'inside':bool(inside_names),'inside_regions':inside_names,'regions':states,'region_revision':revision(regions)}
        evidence.update(regions=regions,region_results=states,region_revision=state['region_revision'],
                        region_changes=changes,latitude=lat,longitude=lon,inside=state['inside'],inside_regions=inside_names)
        return state, "evaluated", evidence, events

    if target["kind"] == "aircraft":
        evidence.update(operator="position_available", capabilities=["position"], flight_risk_assessed=False)
        if observation.get("latitude") is None or observation.get("longitude") is None:
            return None, "missing", evidence, events
        fid=observation.get('flight_source_ref')
        basis=config.get('delay_basis','departure')
        has_times=observation.get('scheduled_'+basis) and (observation.get('actual_'+basis) or observation.get('estimated_'+basis))
        if ('current_flight' in config.get('capabilities',[]) and fid and observation.get('flight_status')
                and (has_times or observation['flight_status'] in {'cancelled','diverted'})):
            # Risk state belongs to a single flight, even though the monitor stays on the aircraft.
            flight_target={**target,'kind':'flight','flight':observation,
                           'state':previous if previous.get('flight_source_ref')==fid else {}}
            state,quality,flight_evidence,events=evaluate(flight_target,observation)
            flight_evidence.update(flight_source_ref=fid,flight_number=observation.get('flight_number'),
                                  aircraft_registration=target['asset']['registration'],flight_risk_assessed=True)
            return {**state,'position_available':True,'flight_risk_assessed':True,'flight_source_ref':fid},quality,flight_evidence,events
        preserved=previous if fid and previous.get('flight_source_ref')==fid else {}
        return {**preserved,"position_available":True,"flight_risk_assessed":False,"flight_source_ref":fid}, "evaluated", evidence, events

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

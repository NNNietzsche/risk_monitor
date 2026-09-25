"""Display descriptions from the historical evaluation, never today's monitor state."""
def timeline_assessment(row, evaluation, events):
    evidence = evaluation["evidence"] if evaluation else {}
    result = {"tone": "normal", "label": "状态更新", "description": "", "rule_version": evidence.get("rule_version")}
    if row["quality"] != "evaluated":
        labels = {"missing":"关键字段缺失", "stale":"数据已过期", "future":"数据时间超前", "out_of_order":"数据乱序", "invalid":"数据无效"}
        return result | {"tone":"warning", "label":"数据待关注", "description": labels.get(row["quality"], "数据未通过质量检查") + "，本次未形成有效风险判断。"}
    if not evaluation:
        return result | {"tone":"unknown", "label":"未评估", "description":"尚无对应的规则判断记录。"}
    if events:
        highest = max(events, key=lambda e: {"info":0,"warning":1,"high":2}[e["severity"]])["severity"]
        delay = evidence.get("delay_minutes")
        threshold = evidence.get("rule_config", {}).get("threshold_minutes")
        if highest == "info" and delay is not None and threshold is not None and delay > threshold:
            return result | {"tone":"warning", "label":"持续关注", "description":"；".join(e["summary"] for e in events) + f"；延误仍为 {delay:g} 分钟，超过 {threshold} 分钟阈值。"}
        return result | {"tone":{"info":"normal","warning":"warning","high":"danger"}[highest], "label":{"info":"状态恢复","warning":"关注","high":"风险"}[highest], "description":"；".join(e["summary"] for e in events)}
    data = row["data"]
    if data["kind"] == "aircraft" and not evidence.get('flight_risk_assessed'):
        return result | {"tone":"unknown", "label":"仅位置", "description":"飞机定位已更新；此监控仅评估位置，未评估航班延误、取消或备降。"}
    if data["kind"] == "vessel":
        inside = evidence.get("inside")
        name = evidence.get("region", {}).get("name", "指定监控区域")
        if inside is True:
            return result | {"tone":"warning", "label":"持续关注", "description":f"船舶仍位于{name}内；本次未发生新的进出变化。"}
        if inside is False:
            return result | {"description":f"定位位于{name}外；本次未触发区域风险事件。"}
    else:
        status = data.get("flight_status")
        if status in {"cancelled","diverted"}:
            return result | {"tone":"danger", "label":"持续异常", "description":"航班仍处于" + ("取消" if status == "cancelled" else "备降") + "状态；本次未重复生成相同事件。"}
        delay = evidence.get("delay_minutes")
        threshold = evidence.get("rule_config", {}).get("threshold_minutes")
        if delay is not None and threshold is not None:
            basis = "起飞" if evidence["rule_config"]["delay_basis"] == "departure" else "到达"
            source = "实际" if evidence.get("time_basis", "").startswith("actual") else "预计"
            if delay > threshold:
                return result | {"tone":"warning", "label":"持续关注", "description":f"按{source}{basis}时间计算，延误仍为 {delay:g} 分钟，超过 {threshold} 分钟阈值；本次未重复告警。"}
            return result | {"description":f"按{source}{basis}时间计算，时间差 {delay:g} 分钟，未超过 {threshold} 分钟阈值。"}
    return result | {"tone":"unknown", "label":"状态更新", "description":"状态数据已更新；没有可展示的确定性判断。"}

"""Presentation rounding only; calculation and stored evidence retain precision."""
from decimal import Decimal, ROUND_HALF_UP


def minutes(value):
    original = Decimal(str(value))
    rounded = original.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    if not rounded:
        rounded = Decimal(0)
    text = format(rounded, 'f').rstrip('0').rstrip('.') if '.' in format(rounded, 'f') else str(rounded)
    return ('约 ' if abs(original - rounded) > Decimal('0.000000001') else '') + text


def event_summary(event):
    evidence = event.get('evidence') or {}
    if event.get('type') == 'flight.delay_exceeded' and evidence.get('delay_minutes') is not None:
        threshold = evidence.get('rule_config', {}).get('threshold_minutes')
        if threshold is not None:
            return f"航班延误 {minutes(evidence['delay_minutes'])} 分钟，超过 {threshold} 分钟阈值"
    return event['summary']

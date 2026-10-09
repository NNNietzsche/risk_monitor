from copy import deepcopy
from datetime import datetime,timezone
from backend.display import minutes, event_summary
from backend.rules import evaluate
from tests.test_sdk_providers import flight_body, make_flight
from backend.app import create_app


def test_delay_display_does_not_change_precision_or_threshold(tmp_path):
    store=create_app(tmp_path/'delay.db',interval=0).state.store
    body=flight_body(int(datetime.now(timezone.utc).timestamp())); target=make_flight(store,body)
    scheduled=target['flight']['scheduled_departure']
    from datetime import timedelta
    actual=(datetime.fromisoformat(scheduled)+timedelta(seconds=7244)).isoformat()
    observation={'flight_status':'active','actual_departure':actual,'estimated_departure':scheduled}
    state,_,evidence,events=evaluate(target,observation)
    assert state['delay_minutes']==7244/60
    assert evidence['time_basis']=='actual_departure'
    assert '约 120.7 分钟' in events[0][2]
    target['rule']['config']['threshold_minutes']=120.72
    assert evaluate(target,observation)[0]['exceeded'] is True
    del observation['actual_departure']
    assert evaluate(target,observation)[2]['time_basis']=='estimated_departure'
    assert evaluate(target,observation)[0]['exceeded'] is False


def test_historical_event_display_does_not_modify_evidence():
    event={'type':'flight.delay_exceeded','summary':'航班延误 120.733 分钟','evidence':{'delay_minutes':7244/60,'rule_config':{'threshold_minutes':60}}}
    before=deepcopy(event)
    assert '约 120.7 分钟' in event_summary(event)
    assert event==before
    assert minutes(120)=='120' and minutes(60.1)=='60.1'
    assert minutes(-0.01)=='约 0' and minutes(60+1/60)=='约 60'

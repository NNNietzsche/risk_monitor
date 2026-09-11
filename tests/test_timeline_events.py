from fastapi.testclient import TestClient
from backend.app import create_app


def test_timeline_groups_observation_and_events_preserves_evidence_and_filters(tmp_path):
    app=create_app(tmp_path/'timeline-events.db',interval=0)
    app.state.portal.seed()
    with TestClient(app) as client:
        timeline=client.get('/api/v1/timeline').json()
        assert timeline['total']==4
        emitted=app.state.store.events()['items']
        grouped=[event for row in timeline['items'] for event in row['events']]
        assert {e['id'] for e in emitted}=={e['id'] for e in grouped}
        assert len([r for r in timeline['items'] if r['events']])==2
        for row in timeline['items']:
            for event in row['events']:
                assert event['evidence']['observation_id']==row['id']
                assert client.get('/api/v1/events/'+event['id']).status_code==200
        filtered=client.get('/api/v1/timeline',params={'kind':'vessel','entry_type':'events','severity':'high'}).json()
        assert filtered['total']==1
        assert filtered['items'][0]['events'][0]['type']=='vessel.entered_region'
        assert filtered['items'][0]['assessment']['tone']=='danger'
        assert client.get('/api/v1/timeline',params={'entry_type':'unknown'}).status_code==422


def test_historical_assessment_does_not_turn_green_during_ongoing_risk_or_rule_changes(tmp_path):
    app=create_app(tmp_path/'historical.db',interval=0)
    app.state.portal.seed()
    store=app.state.store
    vessel=next(m for m in store.monitors() if m['kind']=='vessel')
    flight=next(m for m in store.monitors() if m['kind']=='flight')
    for target,scenario in [(vessel,'inside'),(flight,'delayed')]:
        store.poll(target['id'],scenario)
        row=app.state.portal.timeline()['items'][0]
        assert row['events']==[]
        assert row['assessment']['tone']=='warning'
        assert row['assessment']['label']=='持续关注'
    historical=row
    from backend.models import RuleChange
    store.change_rule(flight['id'],RuleChange(threshold_minutes=200))
    store.poll(flight['id'],'on_time')
    old=next(r for r in app.state.portal.timeline()['items'] if r['id']==historical['id'])
    assert old['assessment']==historical['assessment']
    store.poll(flight['id'],'missing')
    missing=app.state.portal.timeline(entry_type='quality')['items'][0]
    assert missing['assessment']['tone']=='warning'
    assert missing['events']==[]


def test_multiple_events_are_one_timeline_row(tmp_path):
    app=create_app(tmp_path/'multiple.db',interval=0)
    app.state.portal.seed()
    flight=next(m for m in app.state.store.monitors() if m['kind']=='flight')
    app.state.store.poll(flight['id'],'cancelled')
    app.state.store.poll(flight['id'],'recovered')
    row=app.state.portal.timeline()['items'][0]
    assert {e['type'] for e in row['events']}=={'flight.status_restored','flight.delay_recovered'}
    assert row['assessment']['tone']=='normal'


def test_status_restoration_with_remaining_delay_stays_warning(tmp_path):
    app=create_app(tmp_path/'remaining-delay.db',interval=0)
    app.state.portal.seed()
    flight=next(m for m in app.state.store.monitors() if m['kind']=='flight')
    app.state.store.poll(flight['id'],'cancelled')
    app.state.store.poll(flight['id'],'delayed')
    row=app.state.portal.timeline()['items'][0]
    assert [e['type'] for e in row['events']]==['flight.status_restored']
    assert row['assessment']['tone']=='warning'

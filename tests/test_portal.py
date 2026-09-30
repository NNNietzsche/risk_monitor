import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.portal import AISettings
from backend.store import Conflict


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_API_KEY', 'test-secret-never-return')
    monkeypatch.setenv('AI_MODEL', 'test-model')
    return create_app(tmp_path / 'portal.db', interval=0)


def test_page_navigation_and_closed_loop(app):
    with TestClient(app) as client:
        page = client.get('/')
        assert not page.history
        for old in ['/asset-risk.html','/demo.html']:
            redirect=client.get(old,follow_redirects=False)
            assert redirect.status_code==308 and redirect.headers['location']=='/'
        assert page.status_code == 200
        for path in ['index.html','daily-news.html','asset-risk.html','entity-assessment.html','deep-reports.html','intl-ratings.html']:
            assert f'href="{path}"' not in page.text
        assert '<nav' not in page.text
        assert 'public-targets' not in page.text
        assert client.get('/.env').status_code == 404
        assert client.get('/data/risk.db').status_code == 404
        assert client.get('/static/app.js').status_code == 200
        first = client.post('/api/v1/demo/seed').json()
        assert first == client.post('/api/v1/demo/seed').json()
        dashboard = client.get('/api/v1/dashboard').json()
        assert len(dashboard['monitors']) == 2
        assert len(dashboard['timeline']) == 4
        assert {e['type'] for e in dashboard['events']['items']} == {'vessel.entered_region', 'flight.delay_exceeded'}
        assert dashboard['news'][0]['is_mock'] is True
        for event in dashboard['events']['items']:
            detail = client.get('/api/v1/events/' + event['id']).json()
            assert detail['raw_record']['sha256'] == detail['evidence']['raw_sha256']


def test_news_requires_real_source_and_safe_url(app):
    with TestClient(app) as client:
        value = dict(title='News', content='Text', source='Source', published_at='2026-09-11T12:00:00+09:00')
        assert client.post('/api/v1/news', json=value).status_code == 422
        assert client.post('/api/v1/news', json=value | {'source_url':'javascript:alert(1)'}).status_code == 422
        assert client.post('/api/v1/news', json=value | {'source_url':'https://example.org/article'}).status_code == 201


def test_ai_disabled_never_calls_and_unconfigured_cannot_enable(app):
    portal = app.state.portal
    portal.transport = httpx.MockTransport(lambda request: pytest.fail('unexpected network request'))
    assert portal.refresh()['analysis'] is None
    portal.key = ''
    with pytest.raises(Conflict):
        portal.configure(AISettings(enabled=True))


def test_ai_success_caches_audited_input_failure_keeps_previous_and_rules_unchanged(app):
    portal = app.state.portal
    portal.seed()
    before = app.state.store.events()
    calls = []
    def response(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'choices':[{'message':{'content':'模拟数据分析；依据事件 ID。'}}]})
    portal.transport = httpx.MockTransport(response)
    portal.configure(AISettings(enabled=True))
    result = portal.refresh()
    assert result['analysis']['content'] == '模拟数据分析；依据事件 ID。'
    assert 'test-secret' not in json.dumps(result)
    portal.refresh()
    assert len(calls) == 1
    with portal.store.connection() as db:
        run = dict(db.execute('SELECT * FROM ai_runs').fetchone())
        assert hashlib.sha256(run['input_snapshot'].encode()).hexdigest() == run['input_hash']
        assert json.loads(calls[0]['messages'][1]['content']) == json.loads(run['input_snapshot'])
        db.execute("UPDATE ai_runs SET created_at='2020-01-01T00:00:00+00:00'")
    # Meaningful input change without modifying monitoring state.
    from backend.portal import NewsCreate
    portal.add_news(NewsCreate(title='new', content='new', source='mock', published_at='2026-09-11T00:00:00Z', is_mock=True))
    portal.transport = httpx.MockTransport(lambda request: httpx.Response(503, text='test-secret-never-return'))
    failed = portal.refresh()
    assert failed['analysis']['content'] == result['analysis']['content']
    assert failed['last_attempt']['status'] == 'failed'
    assert 'test-secret' not in json.dumps(failed)
    assert app.state.store.events() == before


def test_disable_during_request_discards_result(app):
    portal = app.state.portal
    started, release = Event(), Event()
    def response(request):
        started.set()
        assert release.wait(5)
        return httpx.Response(200, json={'choices':[{'message':{'content':'Should not publish'}}]})
    portal.transport = httpx.MockTransport(response)
    portal.configure(AISettings(enabled=True))
    with ThreadPoolExecutor() as pool:
        future = pool.submit(portal.refresh)
        assert started.wait(5)
        portal.configure(AISettings(enabled=False))
        release.set()
        result = future.result()
    assert result['analysis'] is None
    assert result['last_attempt']['status'] == 'discarded'


@pytest.mark.parametrize('payload', [{}, {'choices':[{'message':{'content':''}}]}, {'choices':[{'message':{'content':{'bad':True}}}]}])
def test_invalid_ai_response_isolated(app, payload):
    portal = app.state.portal
    portal.transport = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    portal.configure(AISettings(enabled=True))
    assert portal.refresh()['last_attempt']['status'] == 'failed'

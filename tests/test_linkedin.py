"""Tests use an isolated SQLite client table and a mocked completion provider."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.models import Client, StyleSnippet, KnowledgeChunk
from app.routers_linkedin import router, get_db, provider, Profile, DraftRequest, suggested_mentions, build_messages

COVERAGE = 'OXCCU was mentioned in an SVT documentary about sustainable aviation fuel. Johan Bergendorff visited the demonstration plant and interviewed the team.'

@pytest.fixture()
def api(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Client.__table__.create(engine)
    StyleSnippet.__table__.create(engine)
    KnowledgeChunk.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([Client(id=1, name='OXCCU', slug='oxccu'), Client(id=2, name='Other', slug='other')])
    session.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(provider, 'OPENROUTER_API_KEY', 'test-key')
    from app import routers_linkedin as linkedin
    async def no_discovery(*args):
        return {'accounts': [], 'posts': [], 'status': 'searched', 'post_search': 'https://www.linkedin.com/search/results/content/'}
    monkeypatch.setattr(linkedin, 'discover', no_discovery)
    with TestClient(app) as client:
        yield client
    session.close()
    engine.dispose()


def test_profile_persists_and_is_client_scoped(api):
    profile = {'voice': 'Plain British English', 'contacts': [{'name': 'SVT', 'role': 'Publication', 'url': 'https://www.linkedin.com/company/svt/'}]}
    assert api.put('/api/v1/linkedin/1/profile', json=profile).status_code == 200
    assert api.get('/api/v1/linkedin/1/profile').json()['voice'] == profile['voice']
    assert api.get('/api/v1/linkedin/2/profile').json()['contacts'] == []
    assert api.get('/api/v1/linkedin/999/profile').status_code == 404
    assert api.put('/api/v1/linkedin/999/profile', json=profile).status_code == 404


@pytest.mark.parametrize('url', ['https://linkedin.com.evil.test/in/person', 'javascript:alert(1)', 'https://www.linkedin.com/feed/', ''])
def test_contact_urls_require_confirmed_linkedin_profiles(api, url):
    assert api.put('/api/v1/linkedin/1/profile', json={'contacts': [{'name': 'Person Name', 'url': url}]}).status_code == 422


def test_suggestions_only_match_full_names_and_deduplicate():
    profile = Profile(contacts=[
        {'name': 'SVT', 'url': 'https://www.linkedin.com/company/svt/', 'role': 'Publication'},
        {'name': 'Johan Bergendorff', 'url': 'https://www.linkedin.com/in/johan-bergendorff-204a8b49/', 'role': 'Journalist'},
        {'name': 'Andrew Symes', 'url': 'https://www.linkedin.com/in/example/', 'role': 'Spokesperson'},
        {'name': 'SVT', 'url': 'https://www.linkedin.com/company/svt/', 'role': 'Publication'},
    ])
    assert [m['name'] for m in suggested_mentions(profile, DraftRequest(coverage=COVERAGE))] == ['SVT', 'Johan Bergendorff']
    assert suggested_mentions(profile, DraftRequest(coverage='S' * 80 + ' unrelated words ' * 12)) == []


def test_generate_uses_saved_context_and_appends_exact_url(api, monkeypatch):
    seen = []
    async def completion(messages, **kwargs):
        seen.extend(messages)
        return 'SVT explores sustainable aviation fuel.\n\nRead more: https://invented.example/story'
    monkeypatch.setattr(provider, 'nonstream_openrouter', completion)
    api.put('/api/v1/linkedin/1/profile', json={'voice': 'Understated and factual'})
    response = api.post('/api/v1/linkedin/1/generate', json={'coverage': COVERAGE, 'url': 'https://svt.se/story'})
    assert response.status_code == 200
    post = response.json()['content']
    assert post.count('https://svt.se/story') == 1
    assert 'invented.example' not in post
    data = json.loads(seen[1]['content'])
    assert data['preferences']['voice'] == 'Understated and factual'
    assert data['client'] == 'OXCCU'
    assert 'sole source' in seen[0]['content']


def test_generation_failures_and_limits(api, monkeypatch):
    assert api.post('/api/v1/linkedin/1/generate', json={'coverage': 'short'}).status_code == 422
    assert api.post('/api/v1/linkedin/999/generate', json={'coverage': COVERAGE}).status_code == 404
    monkeypatch.setattr(provider, 'OPENROUTER_API_KEY', '')
    assert api.post('/api/v1/linkedin/1/generate', json={'coverage': COVERAGE}).status_code == 503
    monkeypatch.setattr(provider, 'OPENROUTER_API_KEY', 'test-key')
    async def empty(messages, **kwargs): return None
    monkeypatch.setattr(provider, 'nonstream_openrouter', empty)
    assert api.post('/api/v1/linkedin/1/generate', json={'coverage': COVERAGE}).status_code == 502
    async def long(messages, **kwargs): return 'x' * 3001
    monkeypatch.setattr(provider, 'nonstream_openrouter', long)
    assert api.post('/api/v1/linkedin/1/generate', json={'coverage': COVERAGE}).status_code == 502


def test_link_only_reads_article_before_generation(api, monkeypatch):
    from app import routers_linkedin as linkedin
    called = []
    async def fetch(url):
        called.append(url)
        return SimpleNamespace(title='OXCCU in SVT', publication='SVT', attribution={'publication': {'names': ['SVT'], 'status': 'source_identified', 'evidence': []}, 'journalist': {'names': ['Johan Bergendorff'], 'status': 'source_identified', 'evidence': []}}, body=COVERAGE + ' The programme explains the development work at the site and explores the role of lower emission fuels in the aviation sector.')
    async def complete(messages, **kwargs):
        data = json.loads(messages[1]['content'])
        assert data['coverage']['publication'] == 'SVT'
        assert 'documentary' in data['coverage']['coverage']
        return 'OXCCU features in an SVT documentary about sustainable aviation fuel.'
    monkeypatch.setattr(linkedin, 'fetch_article_http', fetch)
    monkeypatch.setattr(provider, 'nonstream_openrouter', complete)
    response = api.post('/api/v1/linkedin/1/generate', json={'url': 'https://svt.se/story'})
    assert response.status_code == 200
    assert called == ['https://svt.se/story']
    assert response.json()['source']['title'] == 'OXCCU in SVT'
    assert response.json()['content'].count('https://svt.se/story') == 1


def test_blocked_article_asks_for_fallback_and_does_not_generate(api, monkeypatch):
    from app import routers_linkedin as linkedin
    async def fetch(url):
        raise ValueError('blocked')
    async def complete(messages, **kwargs):
        pytest.fail('Must not generate without coverage')
    monkeypatch.setattr(linkedin, 'fetch_article_http', fetch)
    monkeypatch.setattr(provider, 'nonstream_openrouter', complete)
    response = api.post('/api/v1/linkedin/1/generate', json={'url': 'https://svt.se/blocked'})
    assert response.status_code == 422
    assert 'Paste article text instead' in response.json()['detail']


def test_pasted_text_fallback_skips_fetch(api, monkeypatch):
    from app import routers_linkedin as linkedin
    async def fetch(url):
        pytest.fail('Pasted article text should avoid another blocked request')
    async def complete(messages, **kwargs): return 'OXCCU features in SVT coverage.'
    monkeypatch.setattr(linkedin, 'fetch_article_http', fetch)
    monkeypatch.setattr(provider, 'nonstream_openrouter', complete)
    assert api.post('/api/v1/linkedin/1/generate', json={'coverage': COVERAGE, 'url': 'https://svt.se/blocked'}).status_code == 200
    assert DraftRequest(coverage='https://svt.se/story').url == 'https://svt.se/story'
    assert api.post('/api/v1/linkedin/1/generate', json={}).status_code == 422


def test_attribution_uses_article_metadata_and_ignores_quoted_people():
    from app.services.email.scraper import parse_article_html
    html = """<meta property="og:site_name" content="Example News"><meta name="author" content="Jane Smith">
    <article><p>CEO Andrew Symes said the project is progressing.</p></article>"""
    attr = parse_article_html(html, 'https://news.example/story').attribution
    assert attr['publication']['names'] == ['Example News']
    assert attr['journalist']['names'] == ['Jane Smith']
    assert attr['journalist']['evidence'][0]['source'] == 'meta author'


def test_attribution_abstains_on_conflicting_authors_and_publishers():
    from app.services.email.scraper import parse_article_html
    html = """<meta property="og:site_name" content="Example News"><meta name="author" content="Jane Smith">
    <script type="application/ld+json">{"@type":"NewsArticle","url":"https://news.example/story", "publisher":{"name":"Other News"},"author":{"@type":"Person","name":"John Doe"}}</script>"""
    attr = parse_article_html(html, 'https://news.example/story').attribution
    assert attr['publication']['status'] == 'conflicting'
    assert attr['journalist']['status'] == 'conflicting'
    assert not attr['publication']['names'] and not attr['journalist']['names']


def test_attribution_ignores_related_articles_and_footer_authors():
    from app.services.email.scraper import parse_article_html
    html = """<script type="application/ld+json">{"@graph":[
    {"@type":"NewsArticle","url":"https://news.example/story","author":[{"name":"Jane Smith"},{"name":"Alex Jones"}],"publisher":{"name":"Example News"}},
    {"@type":"NewsArticle","url":"https://news.example/other","author":{"name":"Unrelated Person"}}]}</script>
    <footer><a rel="author">Footer Person</a></footer><article><p>Andrew Symes spoke.</p></article>"""
    attr = parse_article_html(html, 'https://news.example/story').attribution
    assert attr['journalist']['names'] == ['Jane Smith', 'Alex Jones']


def test_missing_attribution_is_not_guessed_from_domain_or_body():
    from app.services.email.scraper import parse_article_html
    from app.services.email.attribution import pasted_attribution
    attr = parse_article_html('<article><p>Jane Smith interviewed CEO John Doe.</p></article>', 'https://famous-publication.example/story').attribution
    assert attr['publication']['status'] == 'unavailable'
    assert attr['journalist']['status'] == 'unavailable'
    pasted = pasted_attribution('Publication: Example News\nBy Jane Smith\n' + COVERAGE)
    assert pasted['publication']['names'] == ['Example News']
    assert pasted['journalist']['names'] == ['Jane Smith']


def test_manual_attribution_cannot_override_article(api, monkeypatch):
    from app import routers_linkedin as linkedin
    async def fetch(url):
        return SimpleNamespace(title='Coverage', body=COVERAGE * 3, attribution={'publication': {'names': ['Source News'], 'status': 'source_identified', 'evidence': []}, 'journalist': {'names': [], 'status': 'unavailable', 'evidence': []}})
    async def complete(messages, **kwargs):
        data = json.loads(messages[1]['content'])
        assert data['coverage']['publication'] == 'Source News'
        assert data['coverage']['journalist'] == ''
        return 'The article discusses OXCCU’s sustainable aviation fuel technology.'
    monkeypatch.setattr(linkedin, 'fetch_article_http', fetch)
    monkeypatch.setattr(provider, 'nonstream_openrouter', complete)
    r=api.post('/api/v1/linkedin/1/generate', json={'url':'https://news.example/story', 'publication':'Made Up', 'journalist':'Fake Person'})
    assert r.status_code == 200
    assert 'Coverage: Source News' in r.json()['content']
    assert 'Fake Person' not in r.json()['content']


def test_visible_byline_and_meta_agree():
    from app.services.email.scraper import parse_article_html
    attr = parse_article_html('<meta name="author" content="Jane Smith"><main><div class="byline">By Jane Smith</div><p>John Doe said hello.</p></main>', 'https://news.example/story').attribution
    assert attr['journalist']['names'] == ['Jane Smith']
    assert len(attr['journalist']['evidence']) == 2


def test_hashtags_are_opt_in_and_repost_omits_duplicate_article_link(api, monkeypatch):
    async def complete(messages, **kwargs): return 'OXCCU coverage in SVT. #SAF #ClimateTech'
    monkeypatch.setattr(provider, 'nonstream_openrouter', complete)
    r=api.post('/api/v1/linkedin/1/generate',json={'coverage':COVERAGE,'url':'https://svt.se/story'})
    assert '#' not in r.json()['content']
    assert 'https://svt.se/story' not in r.json()['repost_content']
    r=api.post('/api/v1/linkedin/1/generate',json={'coverage':COVERAGE,'include_hashtags':True})
    assert '#SAF' in r.json()['content']


def test_showcase_pages_are_valid_contacts(api):
    r=api.put('/api/v1/linkedin/1/profile',json={'contacts':[{'name':'Hydrocarbon Engineering','url':'https://www.linkedin.com/showcase/hydrocarbonengineeringmagazine/','role':'Publication'}]})
    assert r.status_code == 200


def test_discovery_matches_publisher_website_and_handles_ambiguity():
    from app.services.linkedin.discovery import account_matches
    results=[{'url':'https://www.linkedin.com/showcase/example-news','title':'Example News','text':'Website: https://www.example.com'}]
    matches=account_matches(results,'Example News','Publication','Example News','example.com')
    assert matches[0]['status']=='matched'
    results.append({'url':'https://www.linkedin.com/company/other-news','title':'Example News','text':'Website https://example.com'})
    assert all(m['status']=='candidate' for m in account_matches(results,'Example News','Publication','Example News','example.com'))
    assert not account_matches([{'url':'https://linkedin.com.evil.test/company/foo','title':'Example News'}],'Example News','Publication','Example News','example.com')


def test_discovery_never_treats_third_party_post_as_publisher_original():
    from app.services.linkedin.discovery import post_matches
    accounts=[{'url':'https://www.linkedin.com/showcase/example-news/','role':'Publication','status':'matched'}]
    results=[{'url':'https://www.linkedin.com/posts/other-page_test-activity-1','title':'OXCCU wins sustainability award','text':'https://example.com/story'},
             {'url':'https://www.linkedin.com/posts/example-news_test-activity-2','title':'OXCCU wins sustainability award','text':'https://example.com/story'}]
    matches=post_matches(results,'OXCCU wins sustainability award','https://example.com/story','Example News',accounts)
    assert len(matches)==1 and matches[0]['status']=='article_link_matched'


def test_discovery_saves_corroborated_accounts(api, monkeypatch):
    from app import routers_linkedin as linkedin
    async def complete(messages, **kwargs): return 'OXCCU features in coverage.'
    async def discover(*args):
        return {'accounts':[{'name':'SVT','url':'https://www.linkedin.com/company/svt/','role':'Publication','status':'matched'}], 'posts':[], 'status':'searched'}
    monkeypatch.setattr(provider,'nonstream_openrouter',complete)
    monkeypatch.setattr(linkedin,'discover',discover)
    assert api.post('/api/v1/linkedin/1/generate',json={'coverage':COVERAGE}).status_code==200
    assert api.get('/api/v1/linkedin/1/profile').json()['contacts'][0]['name']=='SVT'

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
    async def completion(messages):
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
    assert api.post('/api/v1/linkedin/1/generate', json={'coverage': 'https://example.com'}).status_code == 422
    assert api.post('/api/v1/linkedin/999/generate', json={'coverage': COVERAGE}).status_code == 404
    monkeypatch.setattr(provider, 'OPENROUTER_API_KEY', '')
    assert api.post('/api/v1/linkedin/1/generate', json={'coverage': COVERAGE}).status_code == 503
    monkeypatch.setattr(provider, 'OPENROUTER_API_KEY', 'test-key')
    async def empty(messages): return None
    monkeypatch.setattr(provider, 'nonstream_openrouter', empty)
    assert api.post('/api/v1/linkedin/1/generate', json={'coverage': COVERAGE}).status_code == 502
    async def long(messages): return 'x' * 3001
    monkeypatch.setattr(provider, 'nonstream_openrouter', long)
    assert api.post('/api/v1/linkedin/1/generate', json={'coverage': COVERAGE}).status_code == 502

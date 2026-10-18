"""Read-only preview authority is independent from structured object imports."""
import asyncio
import copy

import pytest

from app.models import GeoProject
from test_advisor_scoped_writes import (
    backend, fixture_token, mutate, no_external_http_or_background_dispatch, write_sandbox,
)

PATH = '/content-imports/preview-file'
UPLOAD = {'file': ('fixture.md', b'# Fixture\n\nImported article. tenant_id=30 business_id=20', 'text/markdown')}


@pytest.mark.parametrize('tid', [10, 20])
def test_file_preview_is_read_only_and_does_not_scan_article_ids(tmp_path, monkeypatch, backend, tid):
    from app.security import advisor_write_objects

    async def no_structured_scan(*_args):
        raise AssertionError('article text must not enter CSV/JSON object import scanning')

    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            monkeypatch.setattr(advisor_write_objects, '_upload_rows', no_structured_scan)
            before = await env.snapshot()
            response = await env.request('POST', PATH, files=UPLOAD, params={'tenant_id': tid},
                auth=fixture_token(tid=tid, gid=101 if tid == 10 else 102))
            assert response.status_code == 200, response.text
            assert response.json()['title'] == 'Fixture'
            assert response.json()['source_type'] == 'file'
            assert 'tenant_id=30' in response.json()['body_markdown']
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('problem', ['disabled', 'not-selected', 'not-granted', 'no-query',
    'identity-only', 'inactive-project', 'unassigned', 'extra-query', 'extra-form', 'two-files'])
def test_file_preview_keeps_authority_and_exact_inputs(tmp_path, monkeypatch, backend, problem):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend, enabled=problem != 'disabled') as env:
            if problem == 'inactive-project':
                await mutate(env, GeoProject, 10, status='archived')
            elif problem == 'unassigned':
                async with env.factory() as session:
                    project = await session.get(GeoProject, 10)
                    settings = copy.deepcopy(project.project_settings)
                settings['geo_service_plan']['advisor_user_id'] = 2
                await mutate(env, GeoProject, 10, project_settings=settings)
            before = await env.snapshot()
            params = {'tenant_id': 20 if problem == 'not-selected' else 30 if problem == 'not-granted' else 10}
            if problem == 'extra-query':
                params['project_id'] = 10
            files = list(UPLOAD.items()) * 2 if problem == 'two-files' else UPLOAD
            kwargs = {'data': {'tenant_id': '20'}} if problem == 'extra-form' else {}
            auth = fixture_token(scope_kind='advisor_identity', aud='advisor-session') if problem == 'identity-only' else None
            if problem == 'no-query':
                import httpx
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url='http://fixture') as client:
                    response = await client.post('/api/v1/geo' + PATH, files=files,
                        headers={'Authorization': 'Bearer ' + fixture_token()})
            else:
                response = await env.request('POST', PATH, files=files, params=params, auth=auth, **kwargs)
            assert response.status_code == (409 if problem == 'identity-only' else 403), response.text
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('filename', ['fixture.csv', 'fixture.json', 'fixture.exe'])
def test_file_preview_rejects_unsupported_types(tmp_path, monkeypatch, backend, filename):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            response = await env.request('POST', PATH, files={'file': (filename, b'fixture text', 'text/plain')})
            assert response.status_code == 400, response.text
    asyncio.run(run())


def test_url_preview_is_authorized_and_read_only(tmp_path, monkeypatch, backend):
    from unittest.mock import AsyncMock
    from app.geo.content import routes

    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            preview = AsyncMock(return_value={'title': 'Fixture', 'source_type': 'url',
                'body_markdown': 'Imported article.'})
            monkeypatch.setattr(routes, 'preview_url_document', preview)
            before = await env.snapshot()
            response = await env.request('POST', '/content-imports/preview-url',
                body={'tenant_id': 10, 'url': 'https://example.test/article'})
            assert response.status_code == 200, response.text
            preview.assert_awaited_once_with('https://example.test/article')
            assert await env.snapshot() == before
    asyncio.run(run())

"""Size checks reject before resolving large lists or persisting article text."""
import asyncio

import pytest
from pydantic import ValidationError

from app.geo.content.schemas import ArticleUpdate, PublicationCreate, TaskCreate, TaskFactsUpdate, VariantUpdate
from app.models import GeoChannelVariant
from app.security.advisor_write_routes import WRITE_ROUTES, check_write_fields
from test_advisor_scoped_writes import backend, mutate, write_sandbox


@pytest.mark.parametrize('schema,body', [
    (TaskCreate, {'tenant_id': 10, 'prompt_id': 10, 'fact_ids': [10] * 51}),
    (TaskFactsUpdate, {'fact_ids': [10] * 51}),
    (ArticleUpdate, {'title': 'fixture', 'body_markdown': 'x' * 500_001}),
    (VariantUpdate, {'body_markdown': 'x' * 500_001}),
    (PublicationCreate, {'tenant_id': 10, 'channel': 'website',
                         'published_url': 'https://example.test/' + 'x' * 2000}),
])
def test_schemas_reject_oversize(schema, body):
    with pytest.raises(ValidationError):
        schema.model_validate(body)


def test_boundary_sizes_remain_available():
    assert len(TaskFactsUpdate(fact_ids=[10] * 50).fact_ids) == 50
    assert len(ArticleUpdate(title='fixture', body_markdown='x' * 500_000).body_markdown) == 500_000
    rule = WRITE_ROUTES[('PUT', '/api/v1/geo/content-tasks/{task_id}/article')]
    check_write_fields(rule, {'title': 'fixture', 'expected_article_id': 10, 'body_markdown': 'x' * 500_000})


@pytest.mark.parametrize('method,path,body', [
    ('POST', '/content-tasks', {'tenant_id': 10, 'prompt_id': 10, 'fact_ids': [10] * 51}),
    ('PUT', '/content-tasks/10/facts', {'fact_ids': [10] * 51}),
    ('PUT', '/content-tasks/10/article', {'title': 'fixture', 'expected_article_id': 10,
                                       'body_markdown': 'x' * 500_001}),
    ('PATCH', '/content-tasks/10/variants/website', {'body_markdown': 'x' * 500_001}),
])
def test_mounted_advisor_rejects_without_changes(tmp_path, monkeypatch, backend, method, path, body):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            response = await env.request(method, path, body=body)
            assert response.status_code == 403, response.text
            assert response.json()['detail']['code'] == 'ADVISOR_WRITE_FIELD_FORBIDDEN'
            assert await env.snapshot() == before
    asyncio.run(run())


def test_published_variant_has_clear_chinese_reason(tmp_path, monkeypatch, backend):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            await mutate(env, GeoChannelVariant, 10, status='published')
            before = await env.snapshot()
            response = await env.request('PATCH', '/content-tasks/10/variants/website', body={'title': 'fixture'})
            assert response.status_code == 403, response.text
            assert response.json()['detail']['code'] == 'ADVISOR_WRITE_STATE_FORBIDDEN'
            assert '已发布渠道稿' in response.json()['detail']['message']
            assert await env.snapshot() == before
    asyncio.run(run())

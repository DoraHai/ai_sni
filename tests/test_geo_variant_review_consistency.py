import asyncio
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.geo.content import routes, variant_execute
from app.geo.content.schemas import VariantUpdate, ReviewDecision


def task_fixture():
    return NS(id=12, tenant_id=1, review_status='approved', review_note='old approval',
              reviewed_by=8, reviewed_at='old', review_submitted_by=7,
              target_channels=['website'], status='ready', business_id=None,
              prompt_id=None, title='title', rule_result={}, ready_at=None)


def variant_fixture(status='draft'):
    return NS(channel='website', title='title', body_markdown='old', status=status,
              article_version_id=15, adapt_meta={'quality': 'publish_ready', 'publishable': True})


@pytest.mark.parametrize('payload', [VariantUpdate(title='new'), VariantUpdate(body_markdown='new')])
def test_edit_invalidates_approval_and_publish_ready_metadata(payload):
    task, variant = task_fixture(), variant_fixture()
    session = NS(refresh=AsyncMock(), commit=AsyncMock())

    async def read_variants(*args):
        session.refresh.assert_awaited_once_with(task, with_for_update=True)
        return [variant]

    with patch.object(routes, '_get_task', AsyncMock(return_value=task)), \
         patch.object(routes, '_variants', read_variants), \
         patch.object(routes, '_sync_task_pipeline', AsyncMock()), \
         patch.object(routes, '_task_payload', AsyncMock(return_value={})):
        asyncio.run(routes.update_variant(12, 'website', payload, 1, NS(ensure_tenant=Mock()), session))
    assert task.review_status == 'none' and task.reviewed_by is None
    assert variant.adapt_meta['publishable'] is False
    assert variant.adapt_meta['quality'] == 'adapted_draft_not_publishable'
    assert variant.adapt_meta['delivery'] == 'html_preview_only'
    assert variant.status == 'draft'
    session.commit.assert_awaited_once()


@pytest.mark.parametrize('published,body', [(False, 'old'), (True, 'old'), (True, 'new')])
def test_noop_keeps_review_and_published_content_cannot_be_overwritten(published, body):
    task, variant = task_fixture(), variant_fixture('published' if published else 'draft')
    session = NS(refresh=AsyncMock(), commit=AsyncMock())
    with patch.object(routes, '_get_task', AsyncMock(return_value=task)), \
         patch.object(routes, '_variants', AsyncMock(return_value=[variant])), \
         patch.object(routes, '_task_payload', AsyncMock(return_value={})):
        run = routes.update_variant(12, 'website', VariantUpdate(body_markdown=body), 1,
                                    NS(ensure_tenant=Mock()), session)
        if published and body == 'new':
            with pytest.raises(HTTPException) as exc:
                asyncio.run(run)
            assert exc.value.status_code == 409
            session.commit.assert_not_awaited()
        else:
            asyncio.run(run)
    assert task.review_status == 'approved'
    assert variant.body_markdown == 'old'
    assert variant.adapt_meta['publishable'] is True


def test_review_uses_state_refreshed_under_task_lock():
    task = task_fixture()
    task.review_status = 'pending'

    async def refresh(row, **kwargs):
        assert kwargs == {'with_for_update': True}
        # An edit won the lock and invalidated the pending review.
        row.review_status = 'none'

    session = NS(refresh=AsyncMock(side_effect=refresh), commit=AsyncMock())
    with patch.object(routes, '_get_task', AsyncMock(return_value=task)):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(routes.decide_task_review(12, ReviewDecision(decision='approved'), 1,
                        NS(ensure_tenant=Mock(), user_id=8), session))
    assert exc.value.status_code == 400
    session.commit.assert_not_awaited()


@pytest.mark.parametrize('published', [False, True])
def test_regeneration_invalidates_review_only_when_draft_is_saved(published):
    task, variant = task_fixture(), variant_fixture('published' if published else 'draft')
    article = NS(id=15, title='title', body_markdown='body', outline={}, author_name=None)
    session = NS(get=AsyncMock(side_effect=[task, NS(name='brand')]), refresh=AsyncMock(),
                 scalars=AsyncMock(return_value=[]), execute=AsyncMock(return_value=NS(
                     scalars=lambda: [])), flush=AsyncMock(), commit=AsyncMock())

    async def latest(*args):
        session.refresh.assert_awaited_once_with(task, with_for_update=True)
        return article

    with ExitStack() as stack:
        for name, replacement in {
            '_latest_article': latest, '_list_variants': AsyncMock(return_value=[variant]),
            'enabled_types_from_rows': Mock(return_value=['website']),
            'resolve_for_channel': AsyncMock(return_value={}),
            'adapt_or_polish_for_channel': AsyncMock(return_value=('new title', 'new body',
                {'quality': 'adapted_draft_not_publishable', 'fallback': True})),
        }.items():
            stack.enter_context(patch.object(variant_execute, name, replacement))
        stack.enter_context(patch('app.geo.content.rules.run_checks', return_value=[]))
        stack.enter_context(patch('app.geo.content.rules.is_ready', return_value=False))
        run = variant_execute.execute_variants_for_task(session, task_id=12, tenant_id=1,
                                                       channels=['website'], use_llm=False)
        if published:
            with pytest.raises(ValueError):
                asyncio.run(run)
            assert task.review_status == 'approved' and variant.body_markdown == 'old'
            session.commit.assert_not_awaited()
        else:
            asyncio.run(run)
            assert task.review_status == 'none' and task.reviewed_by is None
            assert variant.body_markdown == 'new body'
            session.commit.assert_awaited_once()

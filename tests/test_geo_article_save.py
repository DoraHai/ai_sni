import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from app.geo.content.routes import save_article
from app.geo.content.schemas import ArticleUpdate


def fixture(*, expected=11, body='new body', existing=True):
    task = NS(id=100, title='title', status='editing')
    latest = NS(id=11, version_no=3, title='title', body_markdown='saved body\n\n## 逐句证据\nmetadata', outline={}, author_name=None) if existing else None
    session = NS(refresh=AsyncMock(), commit=AsyncMock(), add=Mock())
    req = ArticleUpdate(title='title', body_markdown=body, expected_article_id=expected)
    async def run():
        with patch('app.geo.content.routes._get_task', AsyncMock(return_value=task)), \
             patch('app.geo.content.routes._latest_article', AsyncMock(return_value=latest)) as read_latest, \
             patch('app.geo.content.routes._task_payload', AsyncMock(return_value={'id': 100})), \
             patch('app.geo.content.routes._task_facts', AsyncMock(return_value=[])), \
             patch('app.geo.content.routes._refresh_article_citations'), \
             patch('app.geo.content.routes.invalidate_review') as invalidate, \
             patch('app.geo.content.routes._sync_task_pipeline', AsyncMock()):
            async def read_after_lock(*args):
                session.refresh.assert_awaited_once_with(task, with_for_update=True)
                return latest
            read_latest.side_effect = read_after_lock
            result = await save_article(100, req, 7, NS(ensure_tenant=lambda value: None, user_id=9), session)
            return result, invalidate.call_count
    return run, session


def test_unchanged_save_keeps_version_and_review_even_on_retry():
    run, session = fixture(body='saved body', expected=10)
    result, invalidations = asyncio.run(run())
    assert result['article_changed'] is False
    assert invalidations == 0
    session.add.assert_not_called()
    session.commit.assert_awaited_once()


@pytest.mark.parametrize('expected', [None, 10])
def test_stale_save_cannot_overwrite_newer_version(expected):
    run, session = fixture(expected=expected)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 409
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_current_version_creates_one_new_version_and_invalidates_review():
    run, session = fixture()
    result, invalidations = asyncio.run(run())
    assert invalidations == 1
    session.add.assert_called_once()
    article = session.add.call_args.args[0]
    assert article.version_no == 4
    assert article.body_markdown == 'new body'
    session.commit.assert_awaited_once()


def test_first_save_accepts_explicit_empty_base_version():
    run, session = fixture(expected=None, existing=False)
    asyncio.run(run())
    assert session.add.call_args.args[0].version_no == 1

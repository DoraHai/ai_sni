import asyncio
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import HTTPException
from app.geo.content.routes import decide_task_review
from app.geo.content.schemas import ReviewDecision


@pytest.mark.parametrize('changed', ['article', 'task'])
def test_customer_review_rejects_stale_saved_version(changed):
    task=NS(id=12,updated_at=datetime(2026,9,6))
    session=NS(refresh=AsyncMock(),commit=AsyncMock())
    req=ReviewDecision(decision='approved',expected_article_id=17,
                      expected_updated_at='old' if changed=='task' else None)
    with patch('app.geo.content.routes._get_task',AsyncMock(return_value=task)), \
         patch('app.geo.content.routes._latest_article',AsyncMock(return_value=NS(id=18 if changed=='article' else 17))), \
         patch('app.geo.content.routes.apply_decision') as decision:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(decide_task_review(12,req,7,NS(user_id=9,ensure_tenant=lambda _:None),session))
        assert exc.value.status_code==409
        decision.assert_not_called();session.commit.assert_not_awaited()


def test_content_task_filter_remains_tenant_scoped():
    from app.geo.integration import list_tasks
    from sqlalchemy.dialects import postgresql
    session=NS(scalars=AsyncMock(return_value=[]))
    result=asyncio.run(list_tasks(tenant_id=7,status=None,limit=200,after_id=0,
        ctx=NS(ensure_tenant=lambda _:None),session=session,content_task_id=12))
    query=session.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    assert result==[]
    assert 7 in query.params.values() and 12 in query.params.values()
    assert 'tenant_id' in str(query) and 'progress_first' in str(query)

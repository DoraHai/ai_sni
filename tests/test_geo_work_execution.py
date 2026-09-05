import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from app.geo.routes import TicketExecution, save_ticket_execution
from app.geo.work_execution import compare_samples, freeze_samples
from app.models import GeoActionTicket, GeoContentTask, GeoPrompt


def snap(i, engine='deepseek', mentions=False):
    return NS(id=i, engine=engine, mentions_brand=mentions, raw_text='original answer',
              cited_urls=['https://example.com/source'], captured_at=datetime(2026, 9, 1)+timedelta(days=i),
              sample_mode='openai_compat', simulated=False, citation_accuracy='unknown',
              note='method=unprimed_json_v2 analysis=completed')


def test_comparison_does_not_treat_missing_engines_or_small_samples_as_improvement():
    before = freeze_samples([snap(i) for i in range(1, 4)])
    after = freeze_samples([snap(i, mentions=True) for i in range(4, 7)])
    assert compare_samples(before, after)['delta'] == 1
    assert compare_samples(before, after[:1])['delta'] is None
    after[0]['engine'] = 'doubao'
    assert compare_samples(before, after)['comparable'] is False


@pytest.mark.parametrize('field,value', [('simulated', True), ('sample_mode', 'manual'), ('note', 'method=unprimed_json_v2 analysis=needs_review'), ('citation_accuracy', 'inaccurate')])
def test_invalid_samples_rejected(field, value):
    row = snap(1)
    setattr(row, field, value)
    with pytest.raises(ValueError):
        freeze_samples([row])


def test_frozen_evidence_does_not_change_when_source_is_edited():
    row = snap(1)
    frozen = freeze_samples([row])
    row.raw_text = 'changed'
    row.cited_urls.append('https://other.example/')
    assert frozen[0]['raw_text'] == 'original answer'
    assert len(frozen[0]['cited_urls']) == 1


def run_route(*, status='doing', expected_article='omitted', task_tenant=7, prompt_id=2, requested_before=None, requested_after=None, snapshots=None, article_at=None, note='补充了适用条件'):
    row = GeoActionTicket(id=10, tenant_id=7, advice_code='workqueue:v1:prompt-2', status=status, title='修改内容')
    task = NS(id=100, tenant_id=task_tenant, prompt_id=prompt_id)
    prompt = NS(id=prompt_id, tenant_id=7, is_brand_probe=False, question='如何选型？')
    session = NS(commit=AsyncMock(), refresh=AsyncMock(),
                 scalars=AsyncMock(return_value=snapshots if snapshots is not None else [snap(1), snap(3)]),
                 scalar=AsyncMock(return_value=NS(id=99, version_no=2, created_at=article_at or datetime(2026, 9, 3))))
    session.get = AsyncMock(side_effect=lambda model, id: task if model is GeoContentTask else prompt)
    req = TicketExecution(content_task_id=100, before_snapshot_ids=[1] if requested_before is None else requested_before,
                          after_snapshot_ids=[3] if requested_after is None else requested_after, change_note=note)
    if expected_article != 'omitted':
        req.expected_article_id = expected_article
    async def execute():
        with patch('app.geo.routes._work_ticket_for_update', AsyncMock(return_value=row)):
            return await save_ticket_execution(10, req, 7, NS(ensure_tenant=lambda x: None), session)
    return execute, session, row


def test_route_links_task_and_freezes_comparison_without_finishing_ticket():
    execute, session, row = run_route()
    result = asyncio.run(execute())
    assert result['content_task_id'] == 100
    assert result['baseline_snapshot']['samples'][0]['id'] == 1
    assert result['progress']['samples'][0]['id'] == 3
    assert result['progress']['article_id'] == 99
    assert result['progress']['comparison']['delta'] is None
    assert result['status'] == 'doing'
    session.commit.assert_awaited_once()


@pytest.mark.parametrize('kwargs', [
    {'task_tenant': 8}, {'prompt_id': 3}, {'snapshots': []},
    {'requested_after': [1]}, {'requested_before': [], 'requested_after': [3]},
    {'article_at': datetime(2026, 10, 1)}, {'note': '  '},
    {'article_at': datetime(2026, 9, 1)},
    {'requested_before': [3], 'requested_after': [1]},
])
def test_route_rejects_cross_customer_question_and_invalid_evidence(kwargs):
    execute, session, row = run_route(**kwargs)
    with pytest.raises(HTTPException):
        asyncio.run(execute())
    session.commit.assert_not_awaited()
    assert row.content_task_id is None


def test_link_before_retest_exists():
    execute, session, row = run_route(requested_after=[], snapshots=[snap(1)])
    result = asyncio.run(execute())
    assert result['content_task_id'] == 100
    assert result['progress']['samples'] == []
    assert result['progress']['comparison']['comparable'] is False


def test_completed_ticket_cannot_rewrite_execution_evidence():
    execute, session, row = run_route(status='done')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(execute())
    assert exc.value.status_code == 409
    session.commit.assert_not_awaited()
    assert row.content_task_id is None


@pytest.mark.parametrize('version', [None, 98])
def test_stale_plan_cannot_attach_evidence_to_new_article(version):
    execute, session, row = run_route(expected_article=version)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(execute())
    assert exc.value.status_code == 409
    assert row.content_task_id is None
    session.commit.assert_not_awaited()


def test_current_plan_can_save_execution():
    execute, session, row = run_route(expected_article=99)
    asyncio.run(execute())
    session.commit.assert_awaited_once()


def test_before_only_evidence_must_precede_article():
    execute, session, row = run_route(requested_before=[3], requested_after=[], snapshots=[snap(3)])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(execute())
    assert exc.value.status_code == 400
    session.commit.assert_not_awaited()

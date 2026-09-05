import asyncio
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from app.geo.execution_plan import candidates, execution_steps, sample_gaps
from app.geo.routes import get_ticket_execution_plan, prepare_ticket_content, TicketPrepareContent
from app.models import GeoActionTicket, GeoContentTask, GeoPrompt


def snapshot(id=1, **extra):
    values = dict(id=id, engine='deepseek', sample_mode='openai_compat', simulated=False,
                  note='method=unprimed_json_v2 analysis=completed', citation_accuracy='unknown',
                  raw_text='x'*900, cited_urls=[], mentions_brand=False, captured_at=datetime(2026, 9, 1))
    return NS(**(values | extra))


def ticket():
    return GeoActionTicket(id=10, tenant_id=7, title='选型问题内容改进', advice_code='workqueue:v1:prompt-2', status='todo',
                           baseline_snapshot=None, progress=None, action='补充选型条件与证据')


def test_candidates_exclude_mock_and_limit_preview_without_losing_id():
    items, excluded = candidates([snapshot(), snapshot(2, simulated=True)])
    assert excluded == 1 and items[0]['id'] == 1
    assert len(items[0]['raw_text']) == 500
    assert sample_gaps(items, [])[0]['after_needed'] == 3


def test_execution_steps_require_current_content_evidence():
    row = ticket()
    row.content_task_id = 100
    row.baseline_snapshot = {'prompt_id': 2, 'samples': [{'id': 1}]}
    row.progress = {'article_id': 11, 'samples': [{'id': 2}], 'comparison': {'comparable': True}}
    task = NS(id=100, prompt_id=2)
    steps, _ = execution_steps(row, task, NS(id=12), 3, True, [])
    by_id = {s['id']: s['done'] for s in steps}
    assert by_id['baseline'] and by_id['materials']
    assert not by_id['publication'] and not by_id['retest'] and not by_id['comparison']
    steps, next_step = execution_steps(row, task, NS(id=11), 3, True, [object()])
    assert all(s['done'] for s in steps) and next_step == 'acceptance'


def prepare_fixture(existing=None):
    row = ticket()
    prompt = NS(id=2, tenant_id=7, question='如何选型？', is_brand_probe=False)
    session = NS(scalar=AsyncMock(side_effect=[prompt, existing, None]), scalars=AsyncMock(return_value=[snapshot()]),
                 get=AsyncMock(), flush=AsyncMock(), commit=AsyncMock(), refresh=AsyncMock())
    added = []
    def add(task):
        task.id = 100
        added.append(task)
    session.add = add
    async def run():
        with patch('app.geo.routes._work_ticket_for_update', AsyncMock(return_value=row)), \
             patch('app.geo.content.routes._resolve_task_business_id', AsyncMock(return_value=None)), \
             patch('app.geo.content.routes._resolve_active_period_id', AsyncMock(return_value=None)), \
             patch('app.geo.content.routes._sync_task_pipeline', AsyncMock()):
            return await prepare_ticket_content(10, TicketPrepareContent(), 7, NS(ensure_tenant=lambda x: None, user_id=9), session)
    return row, session, added, run


def test_prepare_creates_draft_and_preserves_baseline_in_same_commit():
    row, session, added, run = prepare_fixture()
    result = asyncio.run(run())
    assert result['created'] and result['task_id'] == 100
    assert row.status == 'doing' and row.content_task_id == 100
    assert row.baseline_snapshot['samples'][0]['id'] == 1
    assert '执行待办 #10' in added[0].brief['notes']
    session.commit.assert_awaited_once()


def test_prepare_reuses_existing_content_without_overwriting_brief():
    old = NS(id=88, tenant_id=7, prompt_id=2, brief={'notes': 'preserve'}, status='editing')
    row, session, added, run = prepare_fixture(old)
    result = asyncio.run(run())
    assert not result['created'] and not added
    assert old.brief == {'notes': 'preserve'}
    assert row.content_task_id == 88


def test_repeated_prepare_keeps_same_task_and_baseline():
    row, session, added, run = prepare_fixture()
    first = asyncio.run(run())
    baseline = row.baseline_snapshot
    session.scalar.side_effect = [NS(id=2, tenant_id=7, question='如何选型？', is_brand_probe=False)]
    session.get.return_value = added[0]
    second = asyncio.run(run())
    assert first['task_id'] == second['task_id']
    assert len(added) == 1
    assert row.baseline_snapshot is baseline


def test_prepare_rejects_completed_ticket():
    row, session, added, run = prepare_fixture()
    row.status = 'done'
    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 409
    assert not added
    session.commit.assert_not_awaited()


def test_prepare_rejects_missing_or_other_tenant_prompt():
    row, session, added, run = prepare_fixture()
    session.scalar.side_effect = [None]
    with pytest.raises(HTTPException):
        asyncio.run(run())
    assert not added
    session.commit.assert_not_awaited()


def test_read_plan_lists_evidence_and_identifies_missing_materials():
    row = ticket()
    task = NS(id=100, tenant_id=7, prompt_id=2, title='existing', status='editing', brief={})
    prompt = NS(id=2, tenant_id=7, question='如何选型？', is_brand_probe=False)
    session = NS(scalars=AsyncMock(side_effect=[[task], [prompt], [snapshot()], [snapshot(2)], []]),
                 scalar=AsyncMock(return_value=NS(id=11, created_at=datetime(2026, 9, 2))), get=AsyncMock(return_value=prompt))
    async def run():
        with patch('app.geo.routes._ticket_for_tenant', AsyncMock(return_value=row)), \
             patch('app.geo.content.routes._task_facts', AsyncMock(return_value=[])):
            return await get_ticket_execution_plan(10, 7, None, NS(ensure_tenant=lambda x: None), session)
    result = asyncio.run(run())
    assert result['selected_task_id'] == 100
    assert result['before'][0]['id'] == 1
    assert result['gaps'][0]['after_needed'] == 2
    assert not next(s for s in result['steps'] if s['id'] == 'materials')['done']


def test_read_plan_rejects_cross_tenant_task_selection():
    row = ticket()
    session = NS(scalars=AsyncMock(return_value=[]), get=AsyncMock(return_value=NS(tenant_id=8, prompt_id=2)))
    async def run():
        with patch('app.geo.routes._ticket_for_tenant', AsyncMock(return_value=row)):
            return await get_ticket_execution_plan(10, 7, 200, NS(ensure_tenant=lambda x: None), session)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 404

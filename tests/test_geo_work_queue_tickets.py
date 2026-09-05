import asyncio
from datetime import date
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from app.geo.routes import TicketCreate, TicketUpdate, create_action_ticket, patch_action_ticket, verify_one_ticket
from app.models import GeoActionTicket
from pydantic import ValidationError


def run_async(fn):
    @wraps(fn)
    def run():
        return asyncio.run(fn())
    return run


def fixture(status='todo', code='workqueue:v1:collect'):
    row = GeoActionTicket(id=10, tenant_id=7, title='补充采样', status=status, advice_code=code)
    row.evidence = []
    session = SimpleNamespace(get=AsyncMock(return_value=row), commit=AsyncMock(), refresh=AsyncMock(), execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))
    ctx = SimpleNamespace(ensure_tenant=lambda tenant: None)
    return row, session, ctx


@run_async
async def test_work_ticket_requires_completion_evidence():
    row, session, ctx = fixture()
    with pytest.raises(HTTPException) as error:
        await patch_action_ticket(10, TicketUpdate(manual_pass=True), 7, ctx, session)
    assert error.value.status_code == 400
    assert row.status == 'todo'
    session.commit.assert_not_awaited()
    with pytest.raises(HTTPException):
        await patch_action_ticket(10, TicketUpdate(status='done'), 7, ctx, session)


@run_async
async def test_work_ticket_records_evidence_and_can_reopen():
    row, session, ctx = fixture()
    result = await patch_action_ticket(10, TicketUpdate(manual_pass=True, verification_note='核验快照 42，引用可访问'), 7, ctx, session)
    assert result['status'] == 'done'
    assert result['closed_at']
    assert result['last_note'] == '核验快照 42，引用可访问'
    assert result['evidence'][-1]['note'] == result['last_note']
    result = await patch_action_ticket(10, TicketUpdate(status='reopened'), 7, ctx, session)
    assert result['closed_at'] is None
    assert result['last_verdict'] is None
    assert result['evidence']


@run_async
async def test_other_customer_cannot_update_ticket():
    row, session, ctx = fixture()
    with pytest.raises(HTTPException) as error:
        await patch_action_ticket(10, TicketUpdate(status='doing'), 8, ctx, session)
    assert error.value.status_code == 404
    session.commit.assert_not_awaited()


@run_async
async def test_legacy_ticket_manual_completion_stays_compatible():
    row, session, ctx = fixture(code='legacy')
    result = await patch_action_ticket(10, TicketUpdate(manual_pass=True), 7, ctx, session)
    assert result['last_note'] == '人工确认通过'


@run_async
async def test_accepting_same_open_suggestion_reuses_ticket_under_tenant_lock():
    row, session, ctx = fixture()
    session.execute = AsyncMock(side_effect=[None, SimpleNamespace(scalar_one_or_none=lambda: row)])
    result = await create_action_ticket(TicketCreate(title='重复采样', advice_code=row.advice_code), 7, ctx, session)
    assert result['id'] == 10
    assert 'FOR UPDATE' in str(session.execute.call_args_list[0].args[0])
    assert 'geo_action_tickets.tenant_id' in str(session.execute.call_args_list[1].args[0])
    session.commit.assert_not_awaited()


@run_async
async def test_owner_deadline_save_preserve_and_clear():
    row, session, ctx = fixture()
    result = await patch_action_ticket(10, TicketUpdate(owner_name='  张三  ', due_date='2026-09-08'), 7, ctx, session)
    assert result['owner_name'] == '张三'
    assert result['due_date'] == '2026-09-08'
    assert row.due_date == date(2026, 9, 8)
    result = await patch_action_ticket(10, TicketUpdate(status='doing'), 7, ctx, session)
    assert result['owner_name'] == '张三'
    assert result['due_date'] == '2026-09-08'
    result = await patch_action_ticket(10, TicketUpdate(owner_name=' ', due_date=None), 7, ctx, session)
    assert result['owner_name'] is None
    assert result['due_date'] is None


def test_assignment_validation():
    with pytest.raises(ValidationError):
        TicketUpdate(owner_name='a' * 101)
    with pytest.raises(ValidationError):
        TicketUpdate(due_date='2026-02-30')
    assert TicketCreate(title='新待办', due_date='2026-09-08').due_date == date(2026, 9, 8)


@run_async
async def test_reopen_conflict_does_not_change_closed_ticket():
    row, session, ctx = fixture(status='done')
    session.execute.side_effect = [None, SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(id=11))]
    with pytest.raises(HTTPException) as error:
        await patch_action_ticket(10, TicketUpdate(status='reopened'), 7, ctx, session)
    assert error.value.status_code == 409
    assert '#11' in error.value.detail
    assert row.status == 'done'
    assert row.evidence == []
    session.commit.assert_not_awaited()


@run_async
async def test_update_reloads_locked_row_before_appending_history():
    stale, session, ctx = fixture()
    current = GeoActionTicket(id=10, tenant_id=7, advice_code=stale.advice_code, status='doing', owner_name='最新负责人')
    current.evidence = [{'note': '另一个操作人刚写入的记录'}]
    session.get.side_effect = [stale, current]
    result = await patch_action_ticket(10, TicketUpdate(due_date='2026-09-10'), 7, ctx, session)
    assert result['owner_name'] == '最新负责人'
    assert result['evidence'][0]['note'] == '另一个操作人刚写入的记录'
    assert session.get.call_args.kwargs == {'with_for_update': True, 'populate_existing': True}
    assert 'FOR UPDATE' in str(session.execute.call_args_list[0].args[0])


@run_async
async def test_work_ticket_automatic_verify_cannot_overwrite_manual_history():
    row, session, ctx = fixture()
    with pytest.raises(HTTPException) as error:
        await verify_one_ticket(10, 7, True, ctx, session)
    assert error.value.status_code == 400
    assert row.evidence == []
    session.commit.assert_not_awaited()


@run_async
async def test_legacy_ticket_does_not_take_work_queue_tenant_lock():
    row, session, ctx = fixture(code='legacy')
    await patch_action_ticket(10, TicketUpdate(status='doing'), 7, ctx, session)
    session.execute.assert_not_awaited()


@run_async
async def test_batch_verify_skips_work_queue_without_changing_evidence():
    from app.geo import routes
    row, session, ctx = fixture()
    row.evidence = [{'note': '保留人工处理记录'}]
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: [row]))
    with patch.object(routes, '_run_for_tenant', AsyncMock(return_value=object())), \
         patch.object(routes, '_media_rows', AsyncMock(return_value=[])), \
         patch.object(routes, '_audit_context', return_value={}):
        result = await routes.verify_audit_tickets(1, 7, False, ctx, session)
    assert result['results'][0]['skipped'] is True
    assert result['summary']['manual'] == 1
    assert result['changed'] == 0
    assert row.evidence == [{'note': '保留人工处理记录'}]


@run_async
async def test_failed_verdict_cannot_reopen_duplicate_either():
    row, session, ctx = fixture(status='done')
    session.execute.side_effect = [None, SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(id=12))]
    with pytest.raises(HTTPException) as error:
        await patch_action_ticket(10, TicketUpdate(manual_pass=False, verification_note='重新核对'), 7, ctx, session)
    assert error.value.status_code == 409
    assert row.status == 'done'
    session.commit.assert_not_awaited()


@run_async
async def test_block_reason_required_and_history_survives_resume():
    row, session, ctx = fixture()
    with pytest.raises(HTTPException):
        await patch_action_ticket(10, TicketUpdate(status='blocked', operation_note='  '), 7, ctx, session)
    assert row.status == 'todo'
    session.commit.assert_not_awaited()
    result = await patch_action_ticket(10, TicketUpdate(status='blocked', operation_note='等待客户提供产品参数'), 7, ctx, session)
    assert result['status'] == 'blocked'
    assert result['evidence'][-1]['check'] == 'workflow.status'
    assert '等待客户提供产品参数' in result['evidence'][-1]['note']
    result = await patch_action_ticket(10, TicketUpdate(status='doing'), 7, ctx, session)
    assert result['evidence'][0]['result'] == 'blocked'
    assert result['evidence'][-1]['result'] == 'doing'


@run_async
async def test_assignment_history_records_changes_only_and_keeps_six():
    row, session, ctx = fixture()
    for i in range(8):
        result = await patch_action_ticket(10, TicketUpdate(owner_name=f'负责人{i}'), 7, ctx, session)
    assert len(result['evidence']) == 6
    assert result['evidence'][-1]['check'] == 'workflow.assignment'
    assert '负责人6' in result['evidence'][-1]['note']
    assert '负责人7' in result['evidence'][-1]['note']
    before = list(row.evidence)
    await patch_action_ticket(10, TicketUpdate(owner_name='负责人7'), 7, ctx, session)
    assert row.evidence == before


@run_async
async def test_conflicting_verdict_and_status_rejected_before_mutation():
    row, session, ctx = fixture()
    with pytest.raises(HTTPException):
        await patch_action_ticket(10, TicketUpdate(status='blocked', manual_pass=True, verification_note='已完成', operation_note='缺资料'), 7, ctx, session)
    assert row.status == 'todo'
    assert row.evidence == []
    with pytest.raises(HTTPException):
        await patch_action_ticket(10, TicketUpdate(status=None), 7, ctx, session)


def test_assignment_migration_preserves_existing_rows():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / 'migrations/versions/20260905_0074_geo_ticket_assignment.py'
    spec = importlib.util.spec_from_file_location('ticket_assignment_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with create_engine('sqlite://').begin() as connection:
        connection.execute(text('CREATE TABLE geo_action_tickets (id INTEGER PRIMARY KEY, title TEXT)'))
        connection.execute(text("INSERT INTO geo_action_tickets VALUES (1, 'existing')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        row = connection.execute(text('SELECT title, owner_name, due_date FROM geo_action_tickets')).one()
        assert tuple(row) == ('existing', None, None)
        migration.downgrade()
        assert connection.execute(text('SELECT title FROM geo_action_tickets')).scalar_one() == 'existing'

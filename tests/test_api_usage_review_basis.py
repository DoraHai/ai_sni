"""Minimal shared contract used by all three admission services."""
from uuid import uuid4
import pytest
from sqlalchemy import text
from app import api_controls as controls
from tests.test_platform_call_guards import native, budget


async def install_basis(factory):
    async with factory() as session:
        await session.execute(text('''ALTER TABLE api_usage_events
            ADD COLUMN review_version integer NOT NULL DEFAULT 0,
            ADD COLUMN verified_amount numeric(24,12),
            ADD COLUMN verified_currency varchar(3),ADD COLUMN reviewed_at timestamptz'''))
        await session.commit()


@pytest.mark.parametrize('target',['global','tenant:1','user:10','provider:dashscope.aliyuncs.com'])
def test_native_reviewed_fee_precedes_estimate_and_null_remains_blocked(monkeypatch,target):
    async def scenario(factory,other):
        await install_basis(factory)
        event=str(uuid4())
        async with factory() as s:
            await s.execute(text('''INSERT INTO api_usage_events
                (id,tenant_id,user_id,origin,module,operation,provider,endpoint,state,estimated_amount,currency,reserved_amount)
                VALUES(CAST(:id AS uuid),1,10,'background','geo','fixture','alias',
                    'dashscope.aliyuncs.com/v1/chat/completions','unknown',3,'CNY',9)'''),{'id':event})
            await s.commit()
        async with other() as s:
            assert (await controls.usage(s,target))['active_calls']==1
            await s.execute(text("UPDATE api_usage_events SET state='error',review_version=1,reviewed_at=CURRENT_TIMESTAMP"))
            await s.commit()
            spent=await controls.usage(s,target)
            assert spent['active_calls']==0 and spent['unresolved_calls']==1
            assert spent['monthly_cny']=='0'
            assert controls.budget_status(budget(max_concurrent=1),spent)=='normal'
            assert controls.budget_status(budget(monthly_cny='100'),spent)=='unknown'
            await s.execute(text("UPDATE api_usage_events SET review_version=2,verified_amount=5,verified_currency='CNY'"))
            await s.commit()
            spent=await controls.usage(s,target)
            assert spent['monthly_cny']=='5.000000000000' and spent['unresolved_calls']==0
            assert controls.budget_status(budget(monthly_cny='4'),spent)=='blocked'
            assert controls.budget_status(budget(monthly_cny='100'),spent)=='normal'
            await s.execute(text("UPDATE api_usage_events SET started_at=CURRENT_TIMESTAMP-INTERVAL '40 days',verified_amount=NULL,verified_currency=NULL"))
            await s.commit()
            spent=await controls.usage(s,target)
            assert spent['monthly_calls']==0 and spent['unresolved_calls']==1
            assert controls.budget_status(budget(monthly_cny='100'),spent)=='unknown'
            assert await s.scalar(text('SELECT estimated_amount FROM api_usage_events'))==3
    native(monkeypatch,scenario)


@pytest.mark.parametrize('missing',['review_version','verified_amount','verified_currency','reviewed_at'])
def test_native_partial_review_schema_fails_closed(monkeypatch,missing):
    async def scenario(factory,other):
        await install_basis(factory)
        async with factory() as s:
            await s.execute(text('ALTER TABLE api_usage_events DROP COLUMN '+missing))
            await s.commit()
            with pytest.raises(RuntimeError,match='Incomplete'):
                await controls.usage(s,'global')
    native(monkeypatch,scenario)

"""Shared PostgreSQL admission and real SEM entry-point identity regression."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import api_controls as controls, api_metering as meter
from test_platform_call_guards import budget, change, native


@pytest.mark.parametrize('target', ['global', 'tenant:1', 'user:10', 'provider:dashscope.aliyuncs.com'])
def test_native_three_service_pools_share_atomic_admission(monkeypatch, target):
    async def scenario(sem, seo):
        async with sem() as s:
            schema = await s.scalar(text('SELECT current_schema()'))
        engine = create_async_engine(sem.kw['bind'].url, connect_args={'server_settings': {'search_path': schema}})
        geo = async_sessionmaker(engine, expire_on_commit=False)
        sent, release, started = [], asyncio.Event(), asyncio.Event()
        async def provider(request):
            sent.append(request)
            if len(sent) == 1:
                started.set()
                await release.wait()
            return httpx.Response(200, json={})
        await change(sem, target, budget(max_concurrent=1))
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
                async def call(module, factory):
                    monkeypatch.setattr(controls, 'async_session_factory', factory)
                    monkeypatch.setattr(meter, 'async_session_factory', factory)
                    # Startup chooses the module; client headers/body cannot choose it.
                    monkeypatch.setenv('API_CONTROLS_ENABLED', 'false')
                    await controls.register_runtime(module)
                    monkeypatch.setenv('API_CONTROLS_ENABLED', 'true')
                    token = meter.scope.set(meter.MeterScope(tenant_id=1, user_id=10, origin='interactive'))
                    try:
                        return await meter.metered_request(client, 'post', 'https://dashscope.aliyuncs.com/v1',
                            json={'tenant_id': 999, 'user_id': 999, 'module': 'forged'},
                            headers={'x-module': 'forged', 'x-tenant-id': '999'})
                    finally:
                        meter.scope.reset(token)
                running = asyncio.create_task(call('sem', sem))
                try:
                    await asyncio.wait_for(started.wait(), 5)
                    for module, factory in (('seo', seo), ('geo', geo)):
                        with pytest.raises(controls.ControlDenied) as denied:
                            await call(module, factory)
                        assert denied.value.target == target
                    assert len(sent) == 1
                finally:
                    release.set()
                    await running
                await call('geo', geo)
                async with seo() as s:
                    rows = (await s.execute(text('SELECT module,tenant_id,user_id,state FROM api_usage_events ORDER BY started_at'))).all()
                    assert [r.module for r in rows] == ['sem', 'geo']
                    assert all((r.tenant_id, r.user_id, r.state) == (1, 10, 'succeeded') for r in rows)
        finally:
            await engine.dispose()
    native(monkeypatch, scenario)


@pytest.mark.parametrize('engine_name', ['rules', 'suggestions'])
@pytest.mark.parametrize('user_id', [None, 10])
def test_native_sem_background_engines_bind_tenant_and_restore_actor(monkeypatch, engine_name, user_id):
    async def scenario(factory, other):
        from app.rules import engine as rules
        from app.suggestions import engine as suggestions
        from app.ai import customer_profile, judge
        from app.suggestions.base import SuggestionDraft
        await change(factory, 'tenant:1', budget(max_concurrent=0))
        sent, observed = [], []
        async def provider(request):
            sent.append(request)
            return httpx.Response(200, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            async def paid():
                observed.append(meter.scope.get())
                return await meter.metered_request(client, 'post', 'https://provider.test/v1')
            async def zero(*args, **kwargs):
                return 0
            if engine_name == 'rules':
                class Rule:
                    code = 'fixture-ai'
                    async def evaluate(self, session, tenant, target_date):
                        await paid()
                        return []
                @asynccontextmanager
                async def transaction():
                    yield
                session = SimpleNamespace(begin_nested=transaction)
                monkeypatch.setattr(rules, 'ALL_RULES', [Rule()])
                monkeypatch.setattr(rules, 'merge_duplicate_alerts', zero)
                async def invoke(tenant):
                    return await rules.run_rules_for_tenant(session, tenant, date(2026, 10, 11))
            else:
                class Session:
                    async def scalar(self, query):
                        return date(2026, 10, 11)
                    async def execute(self, query):
                        return SimpleNamespace(all=lambda: [(101, 'fixture', 10, 5, 100, 1, 2)])
                    async def scalars(self, query):
                        kw = SimpleNamespace(keyword_id=101, keyword='fixture', campaign_id=1, adgroup_id=1,
                            category='focus', price=1, quality=5, left_price_guide=1, m_price_guide=1)
                        return SimpleNamespace(all=lambda: [kw])
                def draft(profile, ctx):
                    return SuggestionDraft('fixture', 'optimize', 'P3', 'mid', 'fixture', 101)
                async def brief(*args):
                    return None
                async def enhance(profile, value, brief):
                    await paid()
                    return value
                monkeypatch.setattr(suggestions, 'ALL_RULES', [draft])
                monkeypatch.setattr(suggestions, 'apply_guardrails', lambda draft, profile: draft)
                monkeypatch.setattr(suggestions, '_persist_suggestions', zero)
                monkeypatch.setattr(customer_profile, 'build_customer_brief', brief)
                monkeypatch.setattr(judge, 'enhance_draft', enhance)
                async def invoke(tenant):
                    return await suggestions.run_suggestions_for_tenant(Session(), tenant)
            prior = meter.MeterScope(tenant_id=999, user_id=user_id, module='unknown',
                origin='interactive' if user_id else 'unattributed')
            token = meter.scope.set(prior)
            try:
                if engine_name == 'suggestions':
                    with pytest.raises(controls.ControlDenied) as denied:
                        await invoke(SimpleNamespace(id=1))
                    assert denied.value.target == 'tenant:1'
                else:
                    await invoke(SimpleNamespace(id=1))  # Existing rule failure isolation remains.
                assert not sent and meter.scope.get() == prior
                await invoke(SimpleNamespace(id=2))
                assert len(sent) == 1 and meter.scope.get() == prior
                assert [(c.tenant_id, c.user_id, c.module) for c in observed] == [(1, user_id, 'sem'), (2, user_id, 'sem')]
                assert all(c.origin == ('interactive' if user_id else 'system') for c in observed)
                async with factory() as s:
                    row = (await s.execute(text('SELECT tenant_id,user_id,module FROM api_usage_events'))).one()
                    assert (row.tenant_id, row.user_id, row.module) == (2, user_id, 'sem')
            finally:
                meter.scope.reset(token)
    native(monkeypatch, scenario)


@pytest.mark.parametrize('entry', ['keyword_range', 'keyword_dimensions', 'region_snapshot'])
def test_native_baidu_background_reports_apply_account_tenant_policy(monkeypatch, entry):
    async def scenario(factory, other):
        from app.baidu import sync
        await change(factory, 'tenant:1', budget(max_concurrent=0))
        monkeypatch.setattr(sync, 'decrypt', lambda value: 'fixture-token')
        monkeypatch.setattr(controls, 'SERVICE_MODULE', 'sem')
        real_client = httpx.AsyncClient
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda r: pytest.fail('Baidu must not send'))))
        account = SimpleNamespace(id=7, tenant_id=1, baidu_username='fixture', access_token_encrypted='fixture')
        today = date(2026, 10, 11)
        token = meter.scope.set(meter.MeterScope())
        try:
            with pytest.raises(controls.ControlDenied) as denied:
                if entry == 'keyword_range':
                    await sync.sync_keyword_report_range_for_account(None, account, today, today)
                elif entry == 'keyword_dimensions':
                    await sync.sync_keyword_dimension_reports_for_account(None, account, today)
                else:
                    await sync.sync_region_snapshot(None, None, account, today, today)
            assert denied.value.target == 'tenant:1'
            async with factory() as s:
                assert await s.scalar(text('SELECT count(*) FROM api_usage_events')) == 0
        finally:
            meter.scope.reset(token)
    native(monkeypatch, scenario)

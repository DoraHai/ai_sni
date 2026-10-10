"""Cross-pool admission races and read-only monitoring on isolated PostgreSQL."""
import asyncio
import json
import os
from decimal import Decimal
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import api_controls as controls, api_metering as meter


def budget(**values):
    return {'daily_calls': None, 'monthly_calls': None, 'daily_cny': None,
            'monthly_cny': None, 'warning_percent': 80, **values}


def native(monkeypatch, scenario, *, schema_controls=True):
    raw = os.getenv('PLATFORM_CONSOLE_TEST_DATABASE_URL')
    if not raw:
        pytest.skip('Explicit local test PostgreSQL required')
    url = make_url(raw)
    assert url.host in {'127.0.0.1', 'localhost'} and 'test' in url.database.lower()
    name = 'call_guards_' + uuid4().hex
    monkeypatch.setenv('API_METERING_ENABLED', 'true')
    monkeypatch.setenv('API_CONTROLS_ENABLED', 'true' if schema_controls else 'false')
    monkeypatch.delenv('API_METERING_RATES_JSON', raising=False)
    async def run():
        setup = create_async_engine(raw)
        pools = [create_async_engine(raw, connect_args={'server_settings': {'search_path': name}}) for _ in range(2)]
        factories = [async_sessionmaker(db, expire_on_commit=False) for db in pools]
        try:
            async with setup.begin() as c:
                await c.execute(text(f'CREATE SCHEMA "{name}"'))
            async with pools[0].connect() as c:
                connection = (await c.get_raw_connection()).driver_connection
                root = Path(__file__).parents[1]
                await connection.execute((root/'scripts/api_metering_schema.sql').read_text())
                if schema_controls:
                    await connection.execute((root/'scripts/api_controls_schema.sql').read_text())
                await c.commit()
            async with pools[0].begin() as c:
                await c.execute(text('CREATE TABLE tenants(id bigint PRIMARY KEY)'))
                await c.execute(text('CREATE TABLE users(id bigint PRIMARY KEY)'))
                await c.execute(text('INSERT INTO tenants VALUES(1),(2)'))
                await c.execute(text('INSERT INTO users VALUES(10),(20)'))
            monkeypatch.setattr(meter, 'async_session_factory', factories[0])
            monkeypatch.setattr(controls, 'async_session_factory', factories[0])
            await scenario(*factories)
        finally:
            for db in pools:
                await db.dispose()
            async with setup.begin() as c:
                await c.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
            await setup.dispose()
    asyncio.run(run())


async def change(factory, target, value, revision=0):
    async with factory() as session:
        return await controls.mutate(session, actor_id=10, request_id=str(uuid4()),
            kind='budget', key='budget:' + target, expected_revision=revision, value=value)


@pytest.mark.parametrize('cap', [-1, True, 1.5, '2', 10001])
def test_concurrency_values_are_bounded_and_optional(cap):
    assert controls.validate_value('budget', budget())['max_concurrent'] is None
    with pytest.raises(ValueError):
        controls.validate_value('budget', budget(max_concurrent=cap))


def test_official_deepseek_exact_rates_use_labeled_peak_ceiling(monkeypatch):
    monkeypatch.delenv('API_METERING_RATES_JSON', raising=False)
    for model in ('deepseek-flash', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp'):
        quote = meter.quote_rate('https://api.deepseek.com/v1/chat/completions', model)
        assert quote['pricing_basis'] == 'peak_ceiling'
        assert quote['source'] == 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing'
        assert meter.estimate(quote, 1000, 500, 100) == Decimal('0.00182')
    assert meter.quote_rate('https://other.example/v1', 'deepseek-v4-flash') is None
    assert meter.quote_rate('https://api.deepseek.com/v1', 'deepseek-chat') is None


@pytest.mark.parametrize('code,status', [('api_concurrency_limit', 429), ('api_budget_exhausted', 429), ('api_charge_unresolved', 503), ('api_provider_disabled', 503), ('api_budget_quote_unavailable', 503)])
def test_policy_denial_is_not_mislabeled_as_configuration_failure(monkeypatch, code, status):
    from app import api_connection_config
    @asynccontextmanager
    async def runtime(module):
        yield
    monkeypatch.setattr(api_connection_config, 'runtime_scope', runtime)
    async def denied(scope, receive, send):
        raise controls.ControlDenied('范围已限制，请核查台账', code=code, target='tenant:1')
    messages = []
    async def send(value):
        messages.append(value)
    async def run():
        await meter.MeteringScopeMiddleware(denied, 'sem')({'type': 'http', 'path': '/api/v1/business'}, None, send)
    asyncio.run(run())
    assert messages[0]['status'] == status
    assert (b'cache-control', b'no-store') in messages[0]['headers']
    assert json.loads(messages[1]['body']) == {'detail': '范围已限制，请核查台账', 'code': code, 'scope': 'tenant:1'}


@pytest.mark.parametrize('target', ['global', 'tenant:1', 'user:10', 'provider:dashscope.aliyuncs.com'])
def test_native_concurrency_shared_across_pools_and_all_scopes(monkeypatch, target):
    async def scenario(factory, competing_factory):
        await change(factory, target, budget(max_concurrent=2))
        release, two_started = asyncio.Event(), asyncio.Event()
        sent, active, maximum = [], 0, 0
        async def provider(request):
            nonlocal active, maximum
            sent.append(request)
            if request.headers.get('x-hold'):
                active += 1
                maximum = max(maximum, active)
                if active == 2:
                    two_started.set()
                await release.wait()
                active -= 1
            return httpx.Response(200, json={'usage': {'prompt_tokens': 100, 'completion_tokens': 10,
                'prompt_tokens_details': {'cached_tokens': 0}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            async def call(tid=1, uid=10, host='dashscope.aliyuncs.com', hold=False):
                with meter.background_scope(tenant_id=tid, user_id=uid, module='sem', operation='test'):
                    return await meter.metered_request(client, 'post', 'https://' + host + '/v1/chat/completions',
                        provider='business-alias', model='deepseek-v4-flash', json={'messages': []},
                        headers={'x-hold': 'yes'} if hold else {})
            running = [asyncio.create_task(call(hold=True)) for _ in range(2)]
            try:
                await asyncio.wait_for(two_started.wait(), 5)
                monkeypatch.setattr(controls, 'async_session_factory', competing_factory)
                rejected = await asyncio.gather(*(call() for _ in range(10)), return_exceptions=True)
                assert all(isinstance(item, controls.ControlDenied) and target in str(item) for item in rejected)
                assert len(sent) == 2
                if target != 'global':
                    await call(tid=2 if target == 'tenant:1' else 1,
                        uid=20 if target == 'user:10' else 10,
                        host='elsewhere.test' if target.startswith('provider:') else 'dashscope.aliyuncs.com')
            finally:
                release.set()
                await asyncio.gather(*running)
            assert maximum == 2
            await call()
            async with factory() as s:
                spent = await controls.usage(s, target)
                assert spent['active_calls'] == 0
                result = await controls.read_controls(s)
                assert 'budget_concurrency_v1' in result['capabilities']
                assert result['budgets'][0]['value']['max_concurrent'] == 2
            await change(factory, target, budget(max_concurrent=0), revision=1)
            before = len(sent)
            with pytest.raises(controls.ControlDenied):
                await call()
            assert len(sent) == before
    native(monkeypatch, scenario)


def test_native_unknown_charge_keeps_hold_and_blocks_budget_after_calendar_reset(monkeypatch):
    async def scenario(factory, other):
        await change(factory, 'global', budget(monthly_cny='100'))
        sent = []
        async def timeout(request):
            sent.append(request)
            raise httpx.ReadTimeout('DO_NOT_EXPOSE', request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            async def call():
                with meter.background_scope(tenant_id=1, user_id=10, module='sem', operation='test'):
                    return await meter.metered_request(client, 'post', 'https://dashscope.aliyuncs.com/v1/chat/completions',
                        model='deepseek-v4-flash', json={'messages': []})
            with pytest.raises(httpx.ReadTimeout):
                await call()
            async with factory() as s:
                row = (await s.execute(text('SELECT state,estimated_amount,reserved_amount FROM api_usage_events'))).one()
                assert row.state == 'unknown' and row.estimated_amount is None and row.reserved_amount > 0
                await s.execute(text("UPDATE api_usage_events SET started_at=CURRENT_TIMESTAMP - INTERVAL '40 days'"))
                await s.commit()
                usage = await controls.usage(s, 'global')
                assert usage['monthly_calls'] == 0 and usage['unresolved_calls'] == 1
                assert controls.budget_status(budget(monthly_cny='100'), usage) == 'unknown'
            with pytest.raises(controls.ControlDenied, match='无法确定费用') as denied:
                await call()
            assert denied.value.code == 'api_charge_unresolved'
            assert len(sent) == 1
    native(monkeypatch, scenario)


@pytest.mark.parametrize('target', ['global', 'tenant:1', 'user:10', 'provider:dashscope.aliyuncs.com'])
def test_native_unknown_result_retains_concurrency_without_money_policy(monkeypatch, target):
    async def scenario(factory, other):
        await change(factory, target, budget(max_concurrent=1))
        sent = []
        async def provider(request):
            sent.append(request)
            if len(sent) == 1:
                raise httpx.ReadTimeout('fixture timeout', request=request)
            return httpx.Response(200, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            async def call(tid=1, uid=10, host='dashscope.aliyuncs.com', module='sem'):
                with meter.background_scope(tenant_id=tid, user_id=uid, module=module, operation='test'):
                    return await meter.metered_request(client, 'post', 'https://' + host + '/v1/chat/completions',
                        provider='different-business-alias', json={'messages': []})
            with pytest.raises(httpx.ReadTimeout):
                await call()
            monkeypatch.setattr(controls, 'async_session_factory', other)
            for old in (False, True):
                async with other() as s:
                    if old:
                        await s.execute(text("UPDATE api_usage_events SET started_at=CURRENT_TIMESTAMP - INTERVAL '40 days'"))
                        await s.commit()
                    spent = await controls.usage(s, target)
                    assert spent['active_calls'] == 1
                    assert controls.budget_status(budget(max_concurrent=1), spent) == 'blocked'
                    assert await s.scalar(text('SELECT state FROM api_usage_events')) == 'unknown'
                    assert await s.scalar(text('SELECT reserved_amount FROM api_usage_events')) is None
                with pytest.raises(controls.ControlDenied) as denied:
                    await call(module='geo')
                assert denied.value.code == 'api_concurrency_limit' and denied.value.target == target
                assert len(sent) == 1
            if target != 'global':
                await call(tid=2 if target.startswith('tenant:') else 1,
                    uid=20 if target.startswith('user:') else 10,
                    host='other.example' if target.startswith('provider:') else 'dashscope.aliyuncs.com', module='seo')
                assert len(sent) == 2
    native(monkeypatch, scenario)


@pytest.mark.parametrize('target', ['global', 'tenant:1', 'user:10', 'provider:dashscope.aliyuncs.com'])
def test_native_definite_http_failure_ends_concurrency_without_money_policy(monkeypatch, target):
    async def scenario(factory, other):
        await change(factory, target, budget(max_concurrent=1))
        sent = []
        async def provider(request):
            sent.append(request)
            return httpx.Response(400 if len(sent) == 1 else 200, json={'error': 'fixture'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            async def call(module):
                with meter.background_scope(tenant_id=1, user_id=10, module=module, operation='test'):
                    return await meter.metered_request(client, 'post', 'https://dashscope.aliyuncs.com/v1/chat/completions', json={})
            assert (await call('sem')).status_code == 400
            monkeypatch.setattr(controls, 'async_session_factory', other)
            async with other() as s:
                assert await s.scalar(text('SELECT state FROM api_usage_events')) == 'error'
                assert (await controls.usage(s, target))['active_calls'] == 0
            assert (await call('seo')).status_code == 200
            assert len(sent) == 2
    native(monkeypatch, scenario)


def test_native_crash_pending_does_not_expire_or_release_on_alert_resolution(monkeypatch):
    async def scenario(factory, other):
        await change(factory, 'tenant:1', budget(max_concurrent=1))
        event = str(uuid4())
        async with factory() as s:
            await s.execute(text('''INSERT INTO api_usage_events
                (id,tenant_id,origin,module,operation,provider,endpoint,state,started_at)
                VALUES(CAST(:id AS uuid),1,'system','sem','test','provider.test','provider.test/v1','requested',
                    CURRENT_TIMESTAMP - INTERVAL '40 days')'''), {'id': event})
            await s.commit()
            # The SEM alert mutation API is intentionally not part of SEO.
            # Keep the shared hold test here; exercise resolution on SEM only.
            import importlib.util
            if importlib.util.find_spec('app.platform_operations') is not None:
                from app.platform_operations import alert_identity, mutate_operation
                alert = alert_identity({'kind': 'api_pending'}, 'fixture-pending', event)
                alerts = [alert]
                await mutate_operation(s, 10, {'request_id': str(uuid4()), 'kind': 'alert', 'key': alert['id'],
                    'expected_revision': 0, 'value': {'action': 'resolve', 'signal': alert['signal'], 'note': 'operator checking'}}, alerts)
            assert (await controls.usage(s, 'tenant:1'))['active_calls'] == 1
            assert await s.scalar(text('SELECT state FROM api_usage_events WHERE id=CAST(:id AS uuid)'), {'id': event}) == 'requested'
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail('must not send'))) as client:
            with meter.background_scope(tenant_id=1, module='sem', operation='test'):
                with pytest.raises(controls.ControlDenied, match='tenant:1'):
                    await meter.metered_request(client, 'post', 'https://provider.test/v1')
    native(monkeypatch, scenario)


def test_native_partial_controls_install_is_not_reported_ready(monkeypatch):
    async def scenario(factory, other):
        async with factory() as s:
            assert (await controls.read_controls(s))['state'] == 'enabled'
            await s.execute(text('DROP TABLE api_control_credentials'))
            await s.commit()
            assert (await controls.read_controls(s))['state'] == 'schema_pending'
    native(monkeypatch, scenario)


@pytest.mark.parametrize('missing', ['api_control_settings', 'api_control_bindings',
    'api_control_credentials', 'api_control_audit', 'reserved_amount'])
def test_native_incomplete_controls_deny_before_attempt_or_provider(monkeypatch, missing):
    async def scenario(factory, other):
        async with factory() as s:
            statement = 'ALTER TABLE api_usage_events DROP COLUMN reserved_amount' if missing == 'reserved_amount' else 'DROP TABLE ' + missing
            await s.execute(text(statement))
            await s.commit()
            assert not await controls.schema_ready(s)
            assert (await controls.read_controls(s))['state'] == 'schema_pending'
        monkeypatch.setattr(controls, 'async_session_factory', other)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail('must not send'))) as client:
            with meter.background_scope(tenant_id=1, module='sem', operation='test'):
                with pytest.raises(meter.MeteringUnavailable) as denied:
                    await meter.metered_request(client, 'post', 'https://provider.test/v1')
                assert denied.value.provider_attempted is False
        async with factory() as s:
            assert await s.scalar(text('SELECT count(*) FROM api_usage_events')) == 0
    native(monkeypatch, scenario)


def test_native_metering_only_needs_no_control_schema(monkeypatch):
    async def scenario(factory, other):
        async with factory() as s:
            assert not await controls.schema_ready(s)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))) as client:
            with meter.background_scope(tenant_id=1, module='sem', operation='test'):
                assert (await meter.metered_request(client, 'post', 'https://provider.test/v1')).status_code == 200
        async with factory() as s:
            assert await s.scalar(text('SELECT count(*) FROM api_usage_events')) == 1
            assert await s.scalar(text('SELECT state FROM api_usage_events')) == 'succeeded'
    native(monkeypatch, scenario, schema_controls=False)


def test_native_initial_ledger_failure_is_known_not_sent(monkeypatch):
    async def scenario(factory, other):
        async with factory() as s:
            await s.execute(text("""CREATE FUNCTION reject_meter_insert() RETURNS trigger LANGUAGE plpgsql AS
                $$ BEGIN RAISE EXCEPTION 'fixture initial write failure'; END $$"""))
            await s.execute(text('CREATE TRIGGER reject_meter_insert BEFORE INSERT ON api_usage_events FOR EACH ROW EXECUTE FUNCTION reject_meter_insert()'))
            await s.commit()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail('must not send'))) as client:
            with pytest.raises(meter.MeteringUnavailable) as denied:
                await meter.metered_request(client, 'post', 'https://provider.test/v1')
            assert denied.value.provider_attempted is False
        async with factory() as s:
            assert await s.scalar(text('SELECT count(*) FROM api_usage_events')) == 0
    native(monkeypatch, scenario, schema_controls=False)


@pytest.mark.parametrize('outcome', ['success', 'error', 'timeout'])
def test_native_terminal_commit_failure_is_attempted_and_keeps_occupancy(monkeypatch, outcome):
    async def scenario(factory, other):
        await change(factory, 'global', budget(max_concurrent=1))
        async with factory() as s:
            await s.execute(text("""CREATE FUNCTION reject_meter_update() RETURNS trigger LANGUAGE plpgsql AS
                $$ BEGIN RAISE EXCEPTION 'fixture final write failure'; END $$"""))
            await s.execute(text('CREATE TRIGGER reject_meter_update BEFORE UPDATE ON api_usage_events FOR EACH ROW EXECUTE FUNCTION reject_meter_update()'))
            await s.commit()
        sent = []
        async def provider(request):
            sent.append(request)
            if outcome == 'timeout':
                raise httpx.ReadTimeout('fixture', request=request)
            return httpx.Response(200 if outcome == 'success' else 400, json={})
        monkeypatch.setattr(meter, 'async_session_factory', other)
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            with pytest.raises(meter.MeteringUnavailable) as failed:
                await meter.metered_request(client, 'post', 'https://provider.test/v1')
            assert failed.value.provider_attempted is True
            async with factory() as s:
                assert await s.scalar(text('SELECT count(*) FROM api_usage_events')) == 1
                assert await s.scalar(text('SELECT state FROM api_usage_events')) == 'requested'
                assert (await controls.usage(s, 'global'))['active_calls'] == 1
            with pytest.raises(controls.ControlDenied) as denied:
                await meter.metered_request(client, 'post', 'https://provider.test/v1')
            assert denied.value.code == 'api_concurrency_limit'
            assert len(sent) == 1
    native(monkeypatch, scenario)


def test_native_reviewed_permission_scripts_keep_audit_append_only(monkeypatch):
    root = Path(__file__).parents[1]
    if not all((root/'scripts'/script).is_file() for script in ('api_metering_permissions.sql', 'api_controls_permissions.sql')):
        pytest.skip('SEM runtime permission scripts are not included in the reviewed SEO integration')
    async def scenario(factory, other):
        role = 'guard_runtime_' + uuid4().hex
        root = Path(__file__).parents[1]
        async with factory() as s:
            schema = await s.scalar(text('SELECT current_schema()'))
            assert schema.startswith('call_guards_')
            await s.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
            await s.commit()
        try:
            async with factory() as s:
                c = await s.connection()
                connection = (await c.get_raw_connection()).driver_connection
                for script in ('api_metering_permissions.sql', 'api_controls_permissions.sql'):
                    # Only the isolated owned schema and unique test role change.
                    sql = (root/'scripts'/script).read_text().replace('public.', schema + '.').replace('sem_runtime', role)
                    await connection.execute(sql)
                await s.commit()
            async with factory() as s:
                await s.execute(text('SET TRANSACTION READ ONLY'))
                for table in ('api_usage_events', 'api_control_settings', 'api_control_bindings', 'api_control_credentials', 'api_control_audit'):
                    params = {'role': role, 'table': schema + '.' + table}
                    assert await s.scalar(text("SELECT has_table_privilege(:role,:table,'SELECT')"), params)
                    assert await s.scalar(text("SELECT has_table_privilege(:role,:table,'INSERT')"), params)
                    assert not await s.scalar(text("SELECT has_table_privilege(:role,:table,'DELETE')"), params)
                    update = await s.scalar(text("SELECT has_table_privilege(:role,:table,'UPDATE')"), params)
                    assert update == (table != 'api_control_audit')
                assert not await s.scalar(text("SELECT has_schema_privilege(:role,:schema,'CREATE')"), {'role': role, 'schema': schema})
        finally:
            async with factory() as s:
                await s.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM "{role}"'))
                await s.execute(text(f'DROP ROLE "{role}"'))
                await s.commit()
    native(monkeypatch, scenario)

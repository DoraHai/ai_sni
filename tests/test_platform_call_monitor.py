"""Existing-ledger-only monitoring, no controls DDL and no worker inference."""
import json
from uuid import uuid4
from sqlalchemy import text
from app import api_controls as controls
from app.api import platform_console as console
from app.platform_call_monitor import read_call_monitor, monitor_alerts
from app.platform_operations import alert_identity
from test_platform_call_guards import native

def test_native_monitor_no_controls_schema_readonly_unknowns_and_no_worker_inference(monkeypatch):
    async def scenario(factory, other):
        monkeypatch.setattr(console, 'async_session_factory', factory)
        async with factory() as s:
            for state, amount, latency, age in [('succeeded', '0.01', 10, '1 minute'),
                    ('succeeded', '0.02', 20, '2 minutes'), ('error', None, 30, '3 minutes'),
                    ('unknown', None, 40, '4 minutes'), ('requested', None, None, '11 minutes')]:
                await s.execute(text('''INSERT INTO api_usage_events
                    (id,origin,module,operation,provider,endpoint,state,estimated_amount,currency,pricing_version,latency_ms,started_at)
                    VALUES(CAST(:id AS uuid),'system','sem','test','provider.test','provider.test/v1',:state,:amount,
                        'CNY',:version,:latency,CURRENT_TIMESTAMP - CAST(CAST(:age AS text) AS interval))'''),
                    {'id': str(uuid4()), 'state': state, 'amount': amount, 'latency': latency,
                     'version': 'contract-v1' if amount else None, 'age': age})
            await s.commit()
        async with factory() as s:
            await s.execute(text('SET TRANSACTION READ ONLY'))
            assert await s.scalar(text('SHOW transaction_read_only')) == 'on'
            result = await read_call_monitor(s)
            summary = result['summary']
            assert summary['calls'] == 5 and summary['succeeded'] == 2 and summary['errors'] == 1
            assert summary['unknown'] == 1 and summary['success_percent'] == 66.7
            assert summary['pending'] == summary['stale_pending'] == 1
            assert summary['unpriced'] == summary['missing_rate'] == 3
            assert summary['unresolved_charges'] == 2
            assert summary['average_latency_ms'] == 25 and summary['p95_latency_ms'] == 40
            assert result['workers']['state'] == 'not_connected' and result['workers']['rows'] == []
            assert (await controls.read_controls(s))['state'] == 'schema_pending'
            assert {a['kind'] for a in monitor_alerts(result, alert_identity)} == {'api_pending', 'api_unknown', 'api_unpriced'}
            serialized = json.dumps(result, default=str)
            assert 'credential_ref' not in serialized and 'rate_quote' not in serialized
            # The actual snapshot also works with only the existing ledger.
            snapshot = await console.build_snapshot(s)
            assert snapshot['operations']['call_monitor']['summary']['calls'] == 5
            assert snapshot['controls']['state'] == 'schema_pending'
            assert snapshot['api_costs']['estimated_amount'] is None
        monkeypatch.setenv('API_METERING_ENABLED', 'false')
        async with factory() as s:
            assert (await read_call_monitor(s))['state'] == 'ready'
    native(monkeypatch, scenario, schema_controls=False)


def test_native_governance_does_not_propagate_sem_flag_to_other_services(monkeypatch):
    from app.ai_governance import read_ai_governance
    async def scenario(factory, other):
        async with factory() as s:
            await s.execute(text('SET TRANSACTION READ ONLY'))
            result = await read_ai_governance(s)
            modules = {row['module']: row for row in result['modules']}
            assert modules['sem']['controls']['runtime_enabled'] is True
            for name in ('seo', 'geo'):
                assert modules[name]['controls']['runtime_enabled'] is None
                assert modules[name]['controls']['state'] == 'runtime_unverified'
            await s.rollback()
            await s.execute(text('DROP TABLE api_control_credentials'))
            await s.commit()
            result = await read_ai_governance(s)
            assert result['controls']['schema'] == 'schema_pending'
            assert all(row['controls']['state'] == 'schema_pending' for row in result['modules'])
    native(monkeypatch, scenario)


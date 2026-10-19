"""Pure handler checks: no database or provider connections."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.geo.content import routes


def test_schema_health_never_exposes_exception_details():
    session = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError('fixture internal detail')),
        rollback=AsyncMock())
    result = asyncio.run(routes.content_health(session=session))
    assert result['status'] == 'degraded'
    assert 'fixture internal detail' not in str(result)
    assert result['schema']['prompts_unit_id_error'] == 'schema_unavailable'


def test_advisor_archive_creation_has_no_public_capability(monkeypatch):
    session = SimpleNamespace(add=Mock(), commit=AsyncMock(), refresh=AsyncMock())
    ctx = SimpleNamespace(advisor_scope=object(), ensure_tenant=Mock(), user_id=1)
    asyncio.run(routes.create_deliverable_archive(tenant_id=10, body={'pack': {}}, ctx=ctx, session=session))
    row = session.add.call_args.args[0]
    assert row.share_token is None


def test_advisor_archive_reads_hide_preexisting_admin_capabilities():
    row = SimpleNamespace(id=1, tenant_id=10, title='fixture', period_from=None, period_to=None,
        share_token='fixture-admin-public-capability', pack_json={}, markdown=None, created_at=None)
    session = SimpleNamespace(scalars=AsyncMock(return_value=[row]), get=AsyncMock(return_value=row))
    ctx = SimpleNamespace(advisor_scope=object(), ensure_tenant=Mock())
    listing = asyncio.run(routes.list_deliverable_archives(tenant_id=10, limit=10, ctx=ctx, session=session))
    detail = asyncio.run(routes.get_deliverable_archive(archive_id=1, tenant_id=10, ctx=ctx, session=session))
    assert listing['items'][0]['share_token'] is None
    assert detail['share_token'] is None
    assert row.share_token == 'fixture-admin-public-capability'

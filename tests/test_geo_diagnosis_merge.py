import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from app.geo.diagnosis_merge import page_identity
from app.geo.routes import materialize_tickets
from app.models import GeoActionTicket


@pytest.mark.parametrize('a,b,equal', [
    ('https://EXAMPLE.com:443/a#x', 'https://example.com/a', True),
    ('https://example.com/a?x=1', 'https://example.com/a?x=2', False),
    ('http://example.com/a', 'https://example.com/a', False),
    ('https://example.com/a/', 'https://example.com/a', False),
    ('https://example.com/A', 'https://example.com/a', False),
])
def test_page_identity_preserves_meaningful_differences(a, b, equal):
    assert (page_identity(a) == page_identity(b)) == equal


@pytest.mark.parametrize('url', ['javascript:x', 'https://user:pass@example.com/a', 'https://[invalid', ''])
def test_invalid_identity_is_not_mergeable(url):
    assert page_identity(url) is None


@pytest.mark.parametrize('status,other_url,expected', [
    ('doing', 'https://example.com/a', 0),
    ('done', 'https://example.com/a', 1),
    ('doing', 'https://example.com/a?other=1', 1),
])
def test_cross_audit_merge_keeps_original_work_and_locks_tenant_first(status, other_url, expected):
    run = NS(id=9, tenant_id=7, url='https://example.com/a', final_url=None, advice=[], findings=[])
    older = NS(id=2, tenant_id=7, url=other_url, final_url=None)
    existing = GeoActionTicket(id=3, tenant_id=7, audit_id=2, advice_code='robots', status=status,
        baseline_snapshot={'evidence':'original'}, owner_name='customer', evidence=[{'note':'history'}])
    events = []
    async def execute(query):
        if not events:
            assert 'tenants' in str(query) and 'FOR UPDATE' in str(query)
            events.append('tenant')
            return NS()
        assert events == ['tenant', 'audit']
        events.append('read')
        return NS(all=lambda: [(existing, older)])
    async def refresh(row, **kw):
        if kw.get('with_for_update'):
            assert events == ['tenant']; events.append('audit')
    added = []
    session = NS(execute=AsyncMock(side_effect=execute), refresh=AsyncMock(side_effect=refresh),
                 commit=AsyncMock(), add=added.append)
    with patch('app.geo.routes._run_for_tenant', AsyncMock(return_value=run)), \
         patch('app.geo.routes.materialize_ticket_specs', return_value=[{'advice_code':'robots','title':'repair'}]):
        result = asyncio.run(materialize_tickets(9, 7, True, NS(ensure_tenant=lambda _:None), session))
    assert result['created'] == expected
    assert len(added) == expected
    assert existing.owner_name == 'customer' and existing.evidence == [{'note':'history'}]
    assert existing.baseline_snapshot['evidence'] == 'original'
    if not expected:
        assert existing.baseline_snapshot['diagnosis_ids'] == [2,9]
        assert result['merged'] == 1 and existing.audit_id == 2

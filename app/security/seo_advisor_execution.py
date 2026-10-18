"""Rebuild a queued advisor's stored scope using current grants, never a JWT."""
import json
from types import SimpleNamespace
from starlette.requests import Request
from app.security.advisor_tenant_auth import apply_advisor_claims, enforce_advisor_request


async def check_manual_execution_scope(session, ctx, user, role, batch):
    proof = (batch.items[0] if batch.items else {}).get('_advisor_scope') or {}
    payload = {'scope_kind': 'advisor_tenant', 'aud': 'advisor-business',
               'tid': batch.tenant_id, 'gid': proof.get('grant_id'),
               'exp': proof.get('auth_exp'), 'auth_exp': proof.get('auth_exp')}
    ctx = await apply_advisor_claims(ctx, user, role, payload, session)
    path = '/api/v1/seo/qa/batches/{batch_id}/control'
    raw = json.dumps({'tenant_id': batch.tenant_id, 'site_id': batch.site_id, 'action': 'resume'}).encode()
    async def receive():
        return {'type': 'http.request', 'body': raw, 'more_body': False}
    request = Request({'type': 'http', 'method': 'POST', 'path': path.format(batch_id=batch.id),
                       'path_params': {'batch_id': batch.id}, 'query_string': f'tenant_id={batch.tenant_id}'.encode(),
                       'headers': [], 'route': SimpleNamespace(path=path)}, receive)
    await enforce_advisor_request(request, ctx, session)
    session._seo_advisor_ai_kind = 'generation'
    return ctx


async def recheck_before_provider(session, publication_id=None):
    ctx = vars(session).get('_seo_advisor_context')
    if ctx is None:
        return
    from app.security.advisor_write_commit import recheck_advisor_before_commit
    from app.security.seo_advisor_audit import record
    request = session._seo_advisor_request
    try:
        await recheck_advisor_before_commit(session, ctx)
    except Exception:
        record(request, ctx, 'external_call_blocked', evidence={'publication_id': publication_id})
        raise
    record(request, ctx, 'external_call_authorized', evidence={'publication_id': publication_id})

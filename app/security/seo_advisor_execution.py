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


def capture_manual_automation_scope(ctx):
    if not getattr(ctx, 'is_advisor', False):
        return None
    request, body, rule = ctx.advisor_write_scope
    return {'user_id': ctx.user_id, 'tenant_id': ctx.tenant_id,
            'grant_id': ctx.grant_id, 'auth_exp': ctx.auth_exp,
            'method': request.method, 'template': rule.template,
            'path_params': dict(request.path_params), 'body': dict(body)}


async def check_manual_automation_scope(session, row):
    """Rebuild the captured selection for each worker transaction, without tokens."""
    proof = getattr(row, '_advisor_scope', None)
    if proof is None:
        return
    from fastapi import HTTPException
    from app.models.user import User
    from app.models.role import Role
    from app.security.auth import _build_context
    raw = json.dumps(proof['body']).encode()
    async def receive():
        return {'type': 'http.request', 'body': raw, 'more_body': False}
    request = Request({'type': 'http', 'method': proof['method'],
                       'path': proof['template'].format(**proof['path_params']),
                       'path_params': proof['path_params'],
                       'query_string': f'tenant_id={row.tenant_id}&site_id={row.site_id}'.encode(),
                       'headers': [], 'route': SimpleNamespace(path=proof['template'])}, receive)
    # Identity here is only for denial logging; authorization below is rebuilt
    # from fresh account/role/grant/assignment reads before any work is allowed.
    row._advisor_actor = SimpleNamespace(user_id=proof['user_id'], tenant_id=proof['tenant_id'])
    row._advisor_request = request
    if (row.requested_by != proof['user_id'] or row.tenant_id != proof['tenant_id']
            or row.site_id != proof['body'].get('site_id')
            or row.job_type != proof['body'].get('job_type')):
        raise HTTPException(403, {'code': 'ADVISOR_OBJECT_UNAVAILABLE'})
    user = await session.get(User, proof['user_id'], populate_existing=True)
    if user is None or not user.is_active:
        raise HTTPException(401, {'code': 'ADVISOR_GRANT_REVOKED'})
    role = await session.get(Role, user.role_id, populate_existing=True)
    ctx = await _build_context(user, session)
    ctx = await apply_advisor_claims(ctx, user, role, {
        'scope_kind': 'advisor_tenant', 'aud': 'advisor-business',
        'tid': proof['tenant_id'], 'gid': proof['grant_id'],
        'exp': proof['auth_exp'], 'auth_exp': proof['auth_exp'],
    }, session)
    await enforce_advisor_request(request, ctx, session)
    request.state.seo_advisor_evidence['run_id'] = row.id
    row._advisor_actor, row._advisor_request = ctx, request
    await recheck_before_provider(session)


def record_manual_automation_result(row, result, **counts):
    if getattr(row, '_advisor_actor', None) is not None:
        from app.security.seo_advisor_audit import record
        record(row._advisor_request, row._advisor_actor, result,
               evidence={'run_id': row.id, 'job_type': row.job_type, **counts})

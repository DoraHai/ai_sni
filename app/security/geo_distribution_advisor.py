"""Exact GEO distribution management policy; existing high-risk flag remains."""
from app.geo.content.distribution_protocol import PREFIX, exact
from app.security.advisor_write_routes import WriteRule

FIELDS = {
    ('PUT', PREFIX + '/settings'): {'enabled', 'scope_enabled', 'expected_revision', 'expected_scope_revision'},
    ('POST', PREFIX + '/device-pairings'): {'label', 'platform', 'account_id', 'expected_revision'},
    ('POST', PREFIX + '/devices/{deviceId}/revoke'): {'expected_revision'},
    ('POST', PREFIX + '/tasks'): {'content_task_id', 'variant_id', 'article_version_id', 'payload_hash', 'device_id', 'request_id'},
    ('POST', PREFIX + '/tasks/{taskId}/publish-account'): {'name', 'expected_revision'},
}
RULES = {key: WriteRule(key[0], key[1], frozenset(fields), frozenset(),
                        ('geo.assets', 'geo.content'), 'project') for key, fields in FIELDS.items()}
READS = {PREFIX + '/settings', PREFIX + '/tasks/{taskId}'}


def match(request):
    return RULES.get((request.method, getattr(request.scope.get('route'), 'path', None)))


async def check_objects(session, ctx, request, body, rule):
    from app.geo.content.distribution_routes import scope
    from app.geo.content import distribution_report as s
    from app.geo.content import distribution_protocol as p
    if RULES.get((rule.method, rule.template)) != rule:
        p.fail('SCOPE_FORBIDDEN', 403)
    fields = rule.fields
    if rule.template == PREFIX + '/device-pairings':
        fields = (fields - {'account_id'}) | ({'account_id'} if 'account_id' in body else set())
    exact(body, fields)
    tenant, project = scope(request)
    ctx.ensure_tenant(tenant)
    store = await s.management_store(session, ctx, tenant, project, write=True)
    if rule.template == PREFIX + '/tasks/{taskId}/publish-account':
        task_id = p.ident(request.path_params.get('taskId'))
        await s.management_task(store, project, task_id)
    if rule.template.endswith('/tasks'):
        for k in ('content_task_id', 'variant_id', 'article_version_id'):
            p.integer(body[k])
        await s.native_task(store, project, body['content_task_id'], body['variant_id'],
                            body['article_version_id'], publish=True)


async def guard(session, ctx, request, claims, rule):
    from app.security.advisor_write_commit import bind_advisor_write_commit
    from app.geo.content.distribution_routes import body as read_body
    from app.security.advisor_scope import deny
    if not all(ctx.can_edit(k) for k in rule.edit_all):
        deny(403, 'ADVISOR_ROUTE_UNAVAILABLE', '当前角色无编辑权限')
    data, _ = await read_body(request)
    # Starlette stream() alone does not cache bytes for the later endpoint.
    # read_body uses Request.body() when the guard has populated this cache.
    await check_objects(session, ctx, request, data, rule)
    from app.security.advisor_read_scope import bind_read_scope
    from app.geo.content.distribution_routes import scope
    _, project_id = scope(request)
    await bind_read_scope(session, ctx, request, project_limit={project_id})
    bind_advisor_write_commit(session, ctx, request, data, rule, claims)
    request.state.advisor_scoped_write = rule
    request.scope['geo_advisor_delivery'] = (ctx.user_id, dict(claims), ctx.tenant_id, frozenset(rule.edit_all))

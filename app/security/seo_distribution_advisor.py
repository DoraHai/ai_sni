"""Exact advisor admission for the manual device-report management surface."""
from sqlalchemy import select

from app.seo_distribution_protocol import PREFIX, KEY, deny

RULES = (
    ('PUT', '/settings', 'enabled scope_enabled expected_revision expected_scope_revision'),
    ('POST', '/device-pairings', 'label platform account_id expected_revision'),
    ('POST', '/devices/{deviceId}/revoke', 'expected_revision'),
    ('POST', '/tasks', 'publication_id source_version payload_hash device_id request_id'),
    ('POST', '/tasks/{taskId}/publish-account', 'name expected_revision'),
)


def rules(rule_type):
    return [rule_type(method, PREFIX + path, frozenset(fields.split()), frozenset(),
                     ('seo.content',), 'site', True) for method, path, fields in RULES]


async def scope(session, ctx, request, body, rule, *, lock=False):
    from app.seo_distribution_report import site_scope, connection_scope
    from app.models.module_workspace import TenantModule
    from app.models.seo import SeoContentPublication, SeoContentAsset
    ctx.ensure_tenant(ctx.tenant_id)
    try:
        tids, sids = request.query_params.getlist('tenant_id'), request.query_params.getlist('site_id')
        if len(tids) != 1 or len(sids) != 1 or int(tids[0]) != ctx.tenant_id or int(sids[0]) < 1:
            deny('SCOPE_FORBIDDEN', 403)
        site_id = int(sids[0])
    except (TypeError, ValueError):
        deny('SCOPE_FORBIDDEN', 403)
    await site_scope(session, ctx.tenant_id, site_id, lock=False)
    request.state.seo_advisor_site_id = site_id
    if rule.template.endswith('/publish-account'):
        settings = await session.scalar(select(TenantModule.module_settings).where(
            TenantModule.tenant_id == ctx.tenant_id, TenantModule.module_code == 'seo'))
        state = settings.get(KEY) if isinstance(settings, dict) else {}
        task = state.get('tasks', {}).get(request.path_params.get('taskId')) if isinstance(state, dict) else None
        if not task or task['site_id'] != site_id:
            deny('SCOPE_FORBIDDEN', 403)
    # UUIDs are registry references, never user-supplied native object grants.
    if '/devices/' in rule.template or rule.template.endswith('/tasks') and body.get('device_id'):
        settings = await session.scalar(select(TenantModule.module_settings).where(
            TenantModule.tenant_id == ctx.tenant_id, TenantModule.module_code == 'seo'))
        state = settings.get(KEY) if isinstance(settings, dict) else {}
        state = state if isinstance(state, dict) else {}
        device_id = request.path_params.get('deviceId') or body.get('device_id')
        device = state.get('devices', {}).get(device_id)
        if not device or device['site_id'] != site_id:
            deny('SCOPE_FORBIDDEN', 403)
    if rule.template.endswith('/device-pairings') and body.get('account_id') is not None:
        await connection_scope(session, ctx.tenant_id, site_id, body.get('account_id'))
    if rule.template.endswith('/tasks') and body.get('publication_id') is not None:
        owner = await session.scalar(select(SeoContentAsset.site_id).join(SeoContentPublication,
            SeoContentPublication.content_asset_id == SeoContentAsset.id).where(
                SeoContentPublication.id == body['publication_id'],
                SeoContentPublication.tenant_id == ctx.tenant_id,
                SeoContentAsset.tenant_id == ctx.tenant_id))
        if owner != site_id:
            deny('SCOPE_FORBIDDEN', 403)
    return site_id


async def lock_scope(session, ctx, request, body, rule):
    from app.models.seo import SeoSiteAdvisorAssignment
    from app.seo_distribution_report import site_scope
    from app.models.module_workspace import TenantModule
    from datetime import date
    site_id = await scope(session, ctx, request, body, rule)
    assignment = await session.scalar(select(SeoSiteAdvisorAssignment.id).where(
        SeoSiteAdvisorAssignment.tenant_id == ctx.tenant_id, SeoSiteAdvisorAssignment.site_id == site_id,
        SeoSiteAdvisorAssignment.advisor_user_id == ctx.user_id, SeoSiteAdvisorAssignment.active.is_(True),
    ).with_for_update(read=True))
    if assignment is None:
        deny('SCOPE_FORBIDDEN', 403)
    await site_scope(session, ctx.tenant_id, site_id)
    # Commit guards run with no_autoflush. A populate_existing ORM reload here
    # would erase the handler's pending JSON ledger. Lock/read Core columns
    # only; the handler itself loaded the ORM row freshly before mutation.
    module = (await session.execute(select(TenantModule.__table__).where(
        TenantModule.tenant_id == ctx.tenant_id, TenantModule.module_code == 'seo'
    ).with_for_update())).mappings().first()
    if (module is None or module['status'] not in {'active', 'trial'}
            or module['expires_at'] is not None and module['expires_at'] < date.today()):
        deny('SCOPE_FORBIDDEN', 403)
    await scope(session, ctx, request, body, rule, lock=True)

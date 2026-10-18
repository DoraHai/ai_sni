"""Project bindings for customer-wide channels, using their existing JSON."""
from sqlalchemy import BigInteger, and_, cast, exists, false, or_, select
from app.security.seo_advisor_work import deny

BINDING_KEY = 'advisor_site_id'


def selected_site(ctx):
    scope = getattr(ctx, 'advisor_write_scope', None)
    site = getattr(scope[0].state, 'seo_advisor_site_id', None) if scope else None
    return site or getattr(ctx, 'advisor_read_site_id', None)


def prior_usage(connection_id, tenant_id, site_id):
    from app.models.seo import SeoContentAsset, SeoContentPublication, SeoDistributionVariant
    content = SeoContentAsset.__table__
    conditions = []
    for model in (SeoContentPublication, SeoDistributionVariant):
        table = model.__table__
        conditions.append(exists(select(table.c.id).join(content,
            content.c.id == table.c.content_asset_id).where(
                table.c.connection_id == connection_id, table.c.tenant_id == tenant_id,
                content.c.tenant_id == tenant_id, content.c.site_id == site_id)))
    return or_(*conditions)


def connection_condition(table, ctx):
    from app.models.module_workspace import SeoSite
    from app.security.seo_advisor_reads import assigned_sites
    site_id = selected_site(ctx)
    if site_id is None:
        return false()
    bound = cast(table.c.config[BINDING_KEY].as_string(), BigInteger)
    return and_(exists(assigned_sites(ctx).where(SeoSite.__table__.c.id == site_id)),
        or_(bound == site_id, and_(bound.is_(None), prior_usage(table.c.id, ctx.tenant_id, site_id))))


async def ensure_connection_binding(session, ctx, rows, site_id):
    for row in rows:
        config = row['config'] if isinstance(row['config'], dict) else {}
        binding = config.get(BINDING_KEY)
        if binding is not None:
            if type(binding) is not int or binding != site_id:
                deny('ADVISOR_ASSIGNMENT_REQUIRED')
        elif not await session.scalar(select(prior_usage(row['id'], ctx.tenant_id, site_id))):
            deny('ADVISOR_ASSIGNMENT_REQUIRED')


async def set_connection_binding(session, ctx, row, tenant_id, site_id):
    if not (ctx.is_superadmin or ctx.can_edit('settings.accounts')):
        deny('ADVISOR_WRITE_PERMISSION_REQUIRED')
    ctx.ensure_tenant(tenant_id)
    if site_id is not None:
        from app.api.seo import _seo_site
        await _seo_site(session, tenant_id, site_id)
    # Zero explicitly revokes all advisor use; absent keys retain verified
    # legacy usage only. Credential/OAuth settings remain untouched.
    row.config = {**(row.config or {}), BINDING_KEY: site_id or 0}

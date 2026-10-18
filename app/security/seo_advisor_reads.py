"""Request-local assignment filters for advisor SEO queries, including totals."""
from sqlalchemy import and_, event, exists, select
from sqlalchemy.orm import with_loader_criteria
from sqlalchemy.sql.selectable import Join


def assigned_sites(ctx):
    from app.models.module_workspace import SeoSite
    from app.models.seo import SeoSiteAdvisorAssignment as Assignment
    sites, assignments = SeoSite.__table__, Assignment.__table__
    return select(sites.c.id).join(assignments, assignments.c.site_id == sites.c.id).where(
        sites.c.tenant_id == ctx.tenant_id, sites.c.status == "active",
        assignments.c.tenant_id == ctx.tenant_id, assignments.c.advisor_user_id == ctx.user_id,
        assignments.c.active.is_(True),
    )


def scope_conditions(table, ctx):
    """Only actual SEO tables; never infer business ownership from a URL."""
    name = getattr(table, "name", "")
    if not name.startswith("seo_") or "tenant_id" not in table.c:
        return []
    conditions = [table.c.tenant_id == ctx.tenant_id]
    if name == "seo_sites":
        conditions.append(table.c.id.in_(assigned_sites(ctx)))
    elif "site_id" in table.c:
        conditions.append(table.c.site_id.in_(assigned_sites(ctx)))
    elif "content_asset_id" in table.c or "content_id" in table.c:
        from app.models.seo import SeoContentAsset
        column = table.c.get("content_asset_id")
        if column is None:
            column = table.c.content_id
        content = SeoContentAsset.__table__
        conditions.append(column.in_(select(content.c.id).where(
            content.c.tenant_id == ctx.tenant_id,
            content.c.site_id.in_(assigned_sites(ctx)),
        )))
    else:
        # Customer-wide publishing accounts have no site owner column. They
        # are usable only in a customer where this advisor has an active site.
        conditions.append(exists(assigned_sites(ctx)))
    return conditions


def install_query_scope(session, ctx):
    """The session belongs to one request. No global session factory changes."""
    from app.database import Base
    target = getattr(session, "sync_session", None)
    if target is None:
        target = getattr(session, "sync", None)  # local SQLite test adapter
    if target is None:
        return
    prior = getattr(target, '_seo_advisor_query_listener', None)
    if prior is not None:
        event.remove(target, 'do_orm_execute', prior)
        target._seo_advisor_query_listener = None
    if ctx is None:
        return
    models = [mapper.class_ for mapper in Base.registry.mappers
              if scope_conditions(mapper.local_table, ctx)]

    def constrain(execution):
        if not (execution.is_select or execution.is_update or execution.is_delete):
            return
        statement = execution.statement
        if execution.is_select:
            for model in models:
                conditions = scope_conditions(model.__table__, ctx)
                statement = statement.options(with_loader_criteria(
                    model, and_(*conditions), include_aliases=True,
                ))
            # Core table selections are also used by existing lock helpers.
            def tables(source):
                if isinstance(source, Join):
                    yield from tables(source.left)
                    yield from tables(source.right)
                elif source in Base.metadata.tables.values():
                    yield source
            for source in statement.get_final_froms():
                for table in tables(source):
                    statement = statement.where(*scope_conditions(table, ctx))
        else:
            statement = statement.where(*scope_conditions(statement.table, ctx))
        execution.statement = statement

    event.listen(target, "do_orm_execute", constrain)
    target._seo_advisor_query_listener = constrain

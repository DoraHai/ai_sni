"""Only reviewed object deletes; no tenant-wide cleanup or configuration deletes."""
PATHS = frozenset({"/api/v1/geo/content-tasks/{task_id}",
                   "/api/v1/geo/answer-snapshots/{snapshot_id}"})


def rules():
    from app.security.advisor_write_routes import FORBIDDEN, WriteRule
    return {("DELETE", path): WriteRule("DELETE", path, frozenset(), FORBIDDEN,
             ("geo.assets", "geo.content"), "project") for path in PATHS}


async def check_cascade_scope(session, request, rule):
    if (rule.template != "/api/v1/geo/content-tasks/{task_id}"
            or request.query_params.get("hard") != "true"):
        return
    from sqlalchemy import select
    from app.models import GeoArticleVersion, GeoChannelVariant
    from app.security.advisor_scope import deny
    target = int(request.path_params["task_id"])
    # FK inserts acquire key-share locks on these parent versions. Hold their
    # update locks until deletion commits so a foreign task cannot enter this
    # cascade after the ownership scan.
    articles = list(await session.scalars(select(GeoArticleVersion.id).where(
        GeoArticleVersion.task_id == target).order_by(GeoArticleVersion.id).with_for_update()))
    foreign_variant = await session.scalar(select(GeoChannelVariant.id).where(
        GeoChannelVariant.article_version_id.in_(articles),
        GeoChannelVariant.task_id != target).limit(1))
    if foreign_variant is not None:
        deny(403, "ADVISOR_DELETE_CASCADE_FORBIDDEN", "稿件关联不一致，不能删除这篇文章，请由管理员核对")

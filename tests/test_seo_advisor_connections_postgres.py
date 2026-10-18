"""Exercise JSON channel bindings and joined reads on the disposable CI DB."""
import asyncio
from sqlalchemy import func, select
from sqlalchemy.schema import CreateTable
from app.models.seo import SeoContentAsset, SeoContentPublication, SeoDistributionConnection, SeoDistributionVariant
from app.security.seo_advisor_reads import install_query_scope
from test_advisor_scoped_writes import actor
from test_advisor_scoped_writes_postgres import store
from test_seo_workflow_postgres import requires_pg

pytestmark = requires_pg


def test_bindings_filter_native_json_lists_counts_aliases_and_joined_publications():
    async def run():
        async with store() as sessions:
            async with sessions() as session:
                connection = await session.connection()
                for model in (SeoDistributionConnection, SeoContentPublication, SeoDistributionVariant):
                    await connection.execute(CreateTable(model.__table__, if_not_exists=True,
                                                          include_foreign_key_constraints=[]))
                for object_id, site_id in [(880, 2), (881, 3), (882, 0)]:
                    session.add(SeoDistributionConnection(id=object_id, tenant_id=4,
                        platform_code='wordpress', name=str(object_id), mode='api', config={'advisor_site_id': site_id}))
                await session.commit()
                ctx = actor(); ctx.advisor_read_site_id = 2
                install_query_scope(session, ctx)
                assert list(await session.scalars(select(SeoDistributionConnection.id))) == [880]
                assert await session.scalar(select(func.count()).select_from(SeoDistributionConnection)) == 1
                query = select(SeoContentPublication, SeoContentAsset, SeoDistributionConnection).join(
                    SeoContentAsset, SeoContentAsset.id == SeoContentPublication.content_asset_id).join(
                    SeoDistributionConnection, SeoDistributionConnection.id == SeoContentPublication.connection_id)
                assert (await session.execute(query)).all() == []
    asyncio.run(run())

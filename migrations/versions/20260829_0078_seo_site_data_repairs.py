"""Repair historical SEO site associations and the reviewed page 231 task link.

Revision ID: 0078_seo_site_data_repairs
Revises: 0077_merge_sem_seo_heads
Create Date: 2026-08-29
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0078_seo_site_data_repairs"
down_revision: Union[str, None] = "0077_merge_sem_seo_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Historical collectors predate mandatory site scoping. Only inherit a site
    # from a keyword when tenant ownership is consistent all the way through.
    op.execute(
        """
        UPDATE seo_rank_snapshots AS snapshot
           SET site_id = keyword.site_id
          FROM seo_keyword_assets AS keyword
          JOIN seo_sites AS site
            ON site.id = keyword.site_id
           AND site.tenant_id = keyword.tenant_id
         WHERE snapshot.site_id IS NULL
           AND snapshot.keyword_id = keyword.id
           AND snapshot.tenant_id = keyword.tenant_id
           AND keyword.site_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE seo_serp_results AS result
           SET site_id = keyword.site_id
          FROM seo_keyword_assets AS keyword
          JOIN seo_sites AS site
            ON site.id = keyword.site_id
           AND site.tenant_id = keyword.tenant_id
         WHERE result.site_id IS NULL
           AND result.keyword_id = keyword.id
           AND result.tenant_id = keyword.tenant_id
           AND keyword.site_id IS NOT NULL
        """
    )

    # One production draft was created during the reviewed page-231 acceptance
    # test before source-page persistence existed. The exact identifiers, title,
    # status, tenant/site ownership and URL make this a fail-closed, auditable
    # repair; it is a no-op in every environment without that exact record.
    op.execute(
        """
        UPDATE seo_content_assets AS content
           SET source_page_id = 231
         WHERE content.id = 3
           AND content.tenant_id = 1
           AND content.site_id = 1
           AND content.status = 'drafting'
           AND content.title = '【验收勿发布】NORDAC NORDCON BU0000 操作手册优化'
           AND content.source_page_id IS NULL
           AND EXISTS (
               SELECT 1
                 FROM seo_site_pages AS page
                WHERE page.id = 231
                  AND page.tenant_id = content.tenant_id
                  AND page.site_id = content.site_id
                  AND page.url = 'https://www.nord.cn/cn/service/documentation/manuals/details/bu0000.jsp'
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM seo_content_assets AS linked
                WHERE linked.tenant_id = content.tenant_id
                  AND linked.site_id = content.site_id
                  AND linked.source_page_id = 231
                  AND linked.id <> content.id
           )
        """
    )


def downgrade() -> None:
    # Data repairs are intentionally not reversed: clearing repaired ownership
    # would recreate ambiguous cross-site history and could unlink later work.
    pass

"""Atomic SEO website purge; ordinary human messages remain append-only.

Production execution requires separate migration approval. No external content deletion.
"""
from alembic import op

revision = "0107_seo_site_delete"
down_revision = "0106_seo_content_messages"
branch_labels = None
depends_on = None

# Frozen child-before-parent inventory. Do not import runtime model metadata here.
SITE_TABLES = (
    "seo_qa_placements",
    "seo_qa_answers",
    "seo_image_verifications",
    "seo_content_review_events",
    "seo_content_confirmations",
    "seo_page_index_reviews",
    "seo_page_ai_tdk_suggestions",
    "seo_internal_links",
    "seo_image_alt_reviews",
    "seo_content_assets",
    "seo_site_pages",
    "seo_serp_results",
    "seo_rank_snapshots",
    "seo_page_snapshots",
    "seo_competitor_events",
    "seo_tdk_review_batches",
    "seo_tasks",
    "seo_site_tdk_review_templates",
    "seo_site_report_templates",
    "seo_site_export_templates",
    "seo_site_analytics_sources",
    "seo_site_analytics_monthly",
    "seo_site_advisor_assignments",
    "seo_questions",
    "seo_qa_facts",
    "seo_qa_batches",
    "seo_page_captures",
    "seo_metric_snapshots",
    "seo_keyword_assets",
    "seo_crawl_runs",
    "seo_competitors",
    "seo_brand_assets",
    "seo_backlinks",
    "seo_automation_runs",
    "seo_ai_operations",
)


def upgrade():
    bind = op.get_bind()
    schema = bind.exec_driver_sql("SELECT current_schema()").scalar_one()
    q = bind.dialect.identifier_preparer.quote_identifier(schema)
    op.execute(f"""CREATE OR REPLACE FUNCTION {q}.seo_reject_message_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' AND pg_trigger_depth() = 2 AND EXISTS (
        SELECT 1 FROM {q}.seo_content_conversations c
        WHERE c.id = OLD.conversation_id
          AND c.site_id::text = current_setting('seo.purge_site_id', true)
          AND c.tenant_id::text = current_setting('seo.purge_tenant_id', true)
      ) THEN RETURN OLD; END IF;
      RAISE EXCEPTION 'SEO human messages are append only' USING ERRCODE='23514';
    END; $$""")
    statements = "\n".join(
        f'DELETE FROM {q}."{table}" WHERE tenant_id = OLD.tenant_id AND site_id = OLD.id;'
        for table in SITE_TABLES
    )
    op.execute(f"""CREATE FUNCTION {q}.seo_purge_site_data()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE old_site text; old_tenant text;
    BEGIN
      old_site := current_setting('seo.purge_site_id', true);
      old_tenant := current_setting('seo.purge_tenant_id', true);
      PERFORM set_config('seo.purge_site_id', OLD.id::text, true);
      PERFORM set_config('seo.purge_tenant_id', OLD.tenant_id::text, true);
      DELETE FROM {q}.seo_content_messages WHERE conversation_id IN (
        SELECT id FROM {q}.seo_content_conversations WHERE tenant_id=OLD.tenant_id AND site_id=OLD.id);
      DELETE FROM {q}.seo_conversation_participants WHERE conversation_id IN (
        SELECT id FROM {q}.seo_content_conversations WHERE tenant_id=OLD.tenant_id AND site_id=OLD.id);
      DELETE FROM {q}.seo_content_conversations WHERE tenant_id=OLD.tenant_id AND site_id=OLD.id;
      {statements}
      PERFORM set_config('seo.purge_site_id', coalesce(old_site, ''), true);
      PERFORM set_config('seo.purge_tenant_id', coalesce(old_tenant, ''), true);
      RETURN OLD;
    END; $$""")
    op.execute(f"""CREATE TRIGGER trg_seo_site_purge BEFORE DELETE ON {q}.seo_sites
      FOR EACH ROW EXECUTE FUNCTION {q}.seo_purge_site_data()""")
    op.execute(f"REVOKE ALL ON FUNCTION {q}.seo_purge_site_data() FROM PUBLIC")
    # Preserve previously archived records as disabled, never silently activate them.
    op.execute(f"UPDATE {q}.seo_sites SET status='paused' WHERE status='archived'")


def downgrade():
    bind = op.get_bind()
    schema = bind.exec_driver_sql("SELECT current_schema()").scalar_one()
    q = bind.dialect.identifier_preparer.quote_identifier(schema)
    op.execute(f"DROP TRIGGER trg_seo_site_purge ON {q}.seo_sites")
    op.execute(f"DROP FUNCTION {q}.seo_purge_site_data()")
    op.execute(f"""CREATE OR REPLACE FUNCTION {q}.seo_reject_message_mutation()
      RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'SEO human messages are append only' USING ERRCODE='23514'; END; $$""")
    # Deleted data cannot be restored; formerly archived sites remain paused.

-- Local candidate only. Not registered in the production migration chain.
CREATE TABLE seo_distribution_result_events (
 event_id uuid PRIMARY KEY, task_id uuid NOT NULL,
 tenant_id bigint NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
 site_id bigint NOT NULL REFERENCES seo_sites(id) ON DELETE RESTRICT,
 variant_id bigint NOT NULL REFERENCES seo_distribution_variants(id) ON DELETE RESTRICT,
 actor_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 fingerprint char(64) NOT NULL, task_fingerprint char(64) NOT NULL,
 publication_id bigint NOT NULL REFERENCES seo_content_publications(id) ON DELETE RESTRICT,
 attempt_id bigint NOT NULL REFERENCES seo_publish_attempts(id) ON DELETE RESTRICT,
 capture_id bigint REFERENCES seo_page_captures(id) ON DELETE RESTRICT,
 payload jsonb NOT NULL, result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX seo_distribution_results_task ON seo_distribution_result_events(task_id,created_at,event_id);
CREATE INDEX seo_distribution_results_scope ON seo_distribution_result_events(tenant_id,site_id,publication_id);
CREATE FUNCTION seo_distribution_result_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'SEO distribution result events are immutable'; END;
$$;
CREATE TRIGGER seo_distribution_results_immutable BEFORE UPDATE OR DELETE ON seo_distribution_result_events
 FOR EACH ROW EXECUTE FUNCTION seo_distribution_result_immutable();

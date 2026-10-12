-- Additive, independently reviewed local candidate. No runtime or production DDL.
CREATE TABLE IF NOT EXISTS geo_distribution_publications (
 task_id uuid PRIMARY KEY,
 tenant_id bigint NOT NULL REFERENCES tenants(id),
 scope_id bigint NOT NULL REFERENCES geo_projects(id),
 variant_id bigint NOT NULL REFERENCES geo_channel_variants(id),
 source_revision varchar(100) NOT NULL,
 content_digest varchar(64) NOT NULL CHECK(content_digest ~ '^[a-f0-9]{64}$'),
 platform varchar(30) NOT NULL CHECK(platform IN ('wechat-article','xiaohongshu-image')),
 public_url text NOT NULL,
 publication_id bigint NOT NULL REFERENCES geo_publications(id),
 placement_id bigint NOT NULL REFERENCES geo_media_placements(id),
 identity_sha256 varchar(64) NOT NULL,
 content_identity_sha256 varchar(64) NOT NULL,
 created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
);
CREATE TABLE IF NOT EXISTS geo_distribution_publication_events (
 event_id uuid PRIMARY KEY,
 task_id uuid NOT NULL REFERENCES geo_distribution_publications(task_id),
 verification varchar(20) NOT NULL CHECK(verification IN ('human-verified','machine-verified')),
 verified_at bigint NOT NULL,
 verified_by bigint NOT NULL,
 reported_at bigint NOT NULL,
 payload_sha256 varchar(64) NOT NULL,
 CHECK(verified_at >= reported_at),
 created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
);
CREATE INDEX IF NOT EXISTS geo_distribution_publication_event_history
 ON geo_distribution_publication_events(task_id,verified_at,event_id);
CREATE OR REPLACE FUNCTION geo_distribution_results_append_only() RETURNS trigger
 LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'GEO distribution result audit records are append only';
 END $$;
DROP TRIGGER IF EXISTS geo_distribution_publications_append_only ON geo_distribution_publications;
CREATE TRIGGER geo_distribution_publications_append_only BEFORE UPDATE OR DELETE
 ON geo_distribution_publications FOR EACH ROW EXECUTE FUNCTION geo_distribution_results_append_only();
DROP TRIGGER IF EXISTS geo_distribution_publication_events_append_only ON geo_distribution_publication_events;
CREATE TRIGGER geo_distribution_publication_events_append_only BEFORE UPDATE OR DELETE
 ON geo_distribution_publication_events FOR EACH ROW EXECUTE FUNCTION geo_distribution_results_append_only();

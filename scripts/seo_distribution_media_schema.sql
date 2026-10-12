-- Local candidate only; not an Alembic revision or production approval.
CREATE TABLE seo_distribution_media_sets (
 id uuid PRIMARY KEY,
 tenant_id bigint NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
 site_id bigint NOT NULL REFERENCES seo_sites(id) ON DELETE RESTRICT,
 variant_id bigint NOT NULL REFERENCES seo_distribution_variants(id) ON DELETE RESTRICT,
 draft_hash char(64) NOT NULL, manifest jsonb NOT NULL,
 uploaded_by bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(jsonb_typeof(manifest)='array' AND jsonb_array_length(manifest) BETWEEN 1 AND 9)
);
CREATE INDEX seo_distribution_media_latest ON seo_distribution_media_sets(variant_id,created_at DESC,id DESC);
CREATE TABLE seo_distribution_media_bytes (
 id uuid PRIMARY KEY, set_id uuid NOT NULL REFERENCES seo_distribution_media_sets(id) ON DELETE RESTRICT,
 position integer NOT NULL CHECK(position BETWEEN 0 AND 8),
 sha256 char(64) NOT NULL CHECK(sha256 ~ '^[a-f0-9]{64}$'),
 media_type varchar(16) NOT NULL CHECK(media_type IN ('image/png','image/jpeg')),
 byte_count integer NOT NULL CHECK(byte_count BETWEEN 1 AND 20000000),
 data bytea NOT NULL CHECK(octet_length(data)=byte_count), UNIQUE(set_id,position)
);
CREATE TABLE seo_distribution_media_reviews (
 set_id uuid PRIMARY KEY REFERENCES seo_distribution_media_sets(id) ON DELETE RESTRICT,
 reviewed_by bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 variant_seal char(64) NOT NULL,
 reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE FUNCTION seo_distribution_media_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'SEO media records are immutable'; END;
$$;
CREATE TRIGGER seo_media_sets_immutable BEFORE UPDATE OR DELETE ON seo_distribution_media_sets
 FOR EACH ROW EXECUTE FUNCTION seo_distribution_media_immutable();
CREATE TRIGGER seo_media_bytes_immutable BEFORE UPDATE OR DELETE ON seo_distribution_media_bytes
 FOR EACH ROW EXECUTE FUNCTION seo_distribution_media_immutable();
CREATE TRIGGER seo_media_reviews_immutable BEFORE UPDATE OR DELETE ON seo_distribution_media_reviews
 FOR EACH ROW EXECUTE FUNCTION seo_distribution_media_immutable();

-- Local candidate only; apply after control and scheduling schemas.
-- No runtime DDL, production execution or mutation of prior receipts.
CREATE TABLE IF NOT EXISTS distribution_publication_checks (
 id uuid PRIMARY KEY, sequence bigserial NOT NULL UNIQUE, task_id uuid NOT NULL REFERENCES distribution_tasks(id),
 actor_id bigint NOT NULL, mode varchar(10) NOT NULL CHECK(mode IN ('machine','human')),
 public_url text NOT NULL, reported_at bigint NOT NULL, checked_at bigint NOT NULL,
 status varchar(16) NOT NULL CHECK(status IN ('verified','needs-human')),
 code varchar(64) NOT NULL,
 verification varchar(24) CHECK(verification IN ('human-verified','machine-verified')),
 observed_digest char(64),
 CHECK ((status='verified')=(verification IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS distribution_publication_check_history
 ON distribution_publication_checks(task_id,sequence DESC);
DROP TRIGGER IF EXISTS distribution_publication_checks_append_only ON distribution_publication_checks;
CREATE TRIGGER distribution_publication_checks_append_only
 BEFORE UPDATE OR DELETE ON distribution_publication_checks
 FOR EACH ROW EXECUTE FUNCTION distribution_append_only();
CREATE TABLE IF NOT EXISTS distribution_publication_writebacks (
 task_id uuid PRIMARY KEY REFERENCES distribution_tasks(id),
 event_id uuid NOT NULL UNIQUE REFERENCES distribution_publication_checks(id),
 actor_id bigint NOT NULL, payload jsonb NOT NULL,
 state varchar(12) NOT NULL CHECK(state IN ('pending','written','blocked')),
 attempts integer NOT NULL DEFAULT 0, updated_at bigint NOT NULL,
 code varchar(64) NOT NULL, result jsonb
);

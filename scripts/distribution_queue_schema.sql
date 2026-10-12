-- Candidate DDL: control -> scheduling -> publication -> queue. No runtime DDL.
CREATE TABLE distribution_channel_permissions (
 platform varchar(60) NOT NULL, content_type varchar(30) NOT NULL,
 enabled boolean NOT NULL DEFAULT false, revision integer NOT NULL,
 updated_by bigint NOT NULL, updated_at bigint NOT NULL,
 PRIMARY KEY(platform,content_type)
);
CREATE TABLE distribution_project_channels (
 tenant_id bigint NOT NULL REFERENCES tenants(id), module varchar(3) NOT NULL CHECK(module IN ('seo','geo')),
 scope_id bigint NOT NULL, binding_id uuid NOT NULL REFERENCES distribution_bindings(id),
 content_type varchar(30) NOT NULL CHECK(content_type IN ('article','image-text')),
 enabled boolean NOT NULL, owner_user_id bigint NOT NULL, revision integer NOT NULL,
 PRIMARY KEY(tenant_id,module,scope_id,binding_id)
);
CREATE TABLE distribution_queue (
 id uuid PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES tenants(id), module varchar(3) NOT NULL,
 scope_id bigint NOT NULL, platform varchar(60) NOT NULL, external_account_id varchar(100) NOT NULL,
 binding_id uuid NOT NULL REFERENCES distribution_bindings(id), variant_id bigint NOT NULL,
 draft_version varchar(100) NOT NULL, source_revision varchar(100), content_digest char(64),
 state varchar(30) NOT NULL, reason varchar(64) NOT NULL, next_allowed_at bigint,
 created_at bigint NOT NULL, checked_at bigint NOT NULL,
 UNIQUE(tenant_id,module,scope_id,platform,external_account_id,variant_id,draft_version)
);
CREATE TABLE distribution_queue_scans (
 tenant_id bigint NOT NULL, module varchar(3) NOT NULL, scope_id bigint NOT NULL, binding_id uuid NOT NULL,
 state varchar(30) NOT NULL, reason varchar(64) NOT NULL, checked_at bigint NOT NULL,
 next_cursor bigint, discovery varchar(30) NOT NULL, recheck_cursor uuid,
 PRIMARY KEY(tenant_id,module,scope_id,binding_id)
);
CREATE INDEX distribution_queue_scope ON distribution_queue(tenant_id,module,scope_id,created_at DESC);

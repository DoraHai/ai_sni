-- Reviewable optional remote-control metadata only. No screenshots or input text.
CREATE TABLE IF NOT EXISTS distribution_remote_sessions (
 id uuid PRIMARY KEY,
 broker_epoch uuid NOT NULL,
 controller_user_id bigint NOT NULL CHECK(controller_user_id>0),
 create_request_id uuid NOT NULL,
 create_fingerprint char(64) NOT NULL,
 module varchar(3) NOT NULL CHECK(module IN ('seo','geo')),
 tenant_id bigint NOT NULL CHECK(tenant_id>0),
 scope_id bigint NOT NULL CHECK(scope_id>0),
 binding_id uuid NOT NULL REFERENCES distribution_bindings(id),
 device_id varchar(100) NOT NULL REFERENCES distribution_devices(id),
 account_id varchar(100) NOT NULL,
 platform varchar(32) NOT NULL CHECK(platform='wechat-article'),
 account_key char(64) NOT NULL,
 purpose varchar(32) NOT NULL CHECK(purpose IN ('account-login','account-verification','task-intervention')),
 task jsonb,
 project_revision integer CHECK(project_revision>0),
 nonce_hash char(64) NOT NULL,
 state varchar(12) NOT NULL CHECK(state IN ('requested','active','closed','expired','failed')),
 code varchar(64) NOT NULL CHECK(code ~ '^[A-Z0-9_]{1,64}$'),
 created_at bigint NOT NULL,
 expires_at bigint NOT NULL,
 closed_at bigint,
 control_revision integer NOT NULL DEFAULT 1 CHECK(control_revision>0),
 last_frame_seq integer NOT NULL DEFAULT 0 CHECK(last_frame_seq>=0),
 viewport_width integer,
 viewport_height integer,
 captured_at bigint,
 uploaded_at bigint,
 command_seq integer NOT NULL DEFAULT 0 CHECK(command_seq>=0),
 last_command_id uuid,
 last_command_state varchar(12),
 UNIQUE(controller_user_id,create_request_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS distribution_remote_device_exclusive
 ON distribution_remote_sessions(device_id) WHERE state IN ('requested','active');
CREATE UNIQUE INDEX IF NOT EXISTS distribution_remote_account_exclusive
 ON distribution_remote_sessions(account_key) WHERE state IN ('requested','active');
CREATE TABLE IF NOT EXISTS distribution_remote_commands (
 id uuid PRIMARY KEY,
 session_id uuid NOT NULL REFERENCES distribution_remote_sessions(id),
 command_seq integer NOT NULL CHECK(command_seq>0),
 control_revision integer NOT NULL CHECK(control_revision>0),
 frame_seq integer NOT NULL CHECK(frame_seq>0),
 kind varchar(8) NOT NULL CHECK(kind IN ('mouse','key','text')),
 state varchar(12) NOT NULL CHECK(state IN ('queued','delivered','applied','rejected','unknown','canceled')),
 code varchar(64) NOT NULL CHECK(code ~ '^[A-Z0-9_]{1,64}$'),
 queued_at bigint NOT NULL,
 delivered_at bigint,
 acked_at bigint,
 UNIQUE(session_id,command_seq)
);

"""Trusted production control records for isolated demonstration datasets."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, PrimaryKeyConstraint, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_SNAPSHOT_KEYS = ("tenant_id", "demo_tenant_id", "dataset_key", "dataset_version", "status", "bound_by_user_id", "bound_at", "updated_by_user_id", "updated_at", "disabled_at", "version", "notes")


def _snapshot_contract(column: str) -> str:
    keys = ",".join(f"'{key}'" for key in _SNAPSHOT_KEYS)
    return (
        f"jsonb_typeof({column}) = 'object' AND {column} ?& ARRAY[{keys}]::text[] "
        f"AND ({column} - ARRAY[{keys}]::text[]) = '{{}}'::jsonb "
        f"AND jsonb_typeof({column}->'tenant_id') = 'number' AND ({column}->>'tenant_id') ~ '^[1-9][0-9]*$' "
        f"AND jsonb_typeof({column}->'demo_tenant_id') = 'number' AND ({column}->>'demo_tenant_id') ~ '^[1-9][0-9]*$' "
        f"AND jsonb_typeof({column}->'dataset_key') = 'string' AND ({column}->>'dataset_key') ~ '^[a-z0-9][a-z0-9_-]{{0,63}}$' "
        f"AND jsonb_typeof({column}->'dataset_version') = 'string' AND ({column}->>'dataset_version') ~ '^[a-z0-9][a-z0-9._-]{{0,39}}$' "
        f"AND jsonb_typeof({column}->'status') = 'string' AND ({column}->>'status') IN ('active','disabled') "
        f"AND jsonb_typeof({column}->'bound_by_user_id') = 'number' AND ({column}->>'bound_by_user_id') ~ '^[1-9][0-9]*$' "
        f"AND jsonb_typeof({column}->'updated_by_user_id') = 'number' AND ({column}->>'updated_by_user_id') ~ '^[1-9][0-9]*$' "
        f"AND jsonb_typeof({column}->'version') = 'number' AND ({column}->>'version') ~ '^[1-9][0-9]*$' "
        f"AND jsonb_typeof({column}->'bound_at') = 'string' AND jsonb_typeof({column}->'updated_at') = 'string' "
        f"AND jsonb_typeof({column}->'disabled_at') IN ('null','string') AND jsonb_typeof({column}->'notes') IN ('null','string')"
    )


class DemoTenantBinding(Base):
    __tablename__ = "demo_tenant_bindings"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", name="pk_demo_tenant_bindings"),
        UniqueConstraint("demo_tenant_id", name="uq_demo_tenant_bindings_demo_tenant"),
        UniqueConstraint("dataset_key", name="uq_demo_tenant_bindings_dataset_key"),
        CheckConstraint("demo_tenant_id > 0", name="ck_demo_tenant_bindings_demo_tenant_positive"),
        CheckConstraint("version > 0", name="ck_demo_tenant_bindings_version_positive"),
        CheckConstraint("dataset_key ~ '^[a-z0-9][a-z0-9_-]{0,63}$'", name="ck_demo_tenant_bindings_dataset_key_format"),
        CheckConstraint("dataset_version ~ '^[a-z0-9][a-z0-9._-]{0,39}$'", name="ck_demo_tenant_bindings_dataset_version_format"),
        CheckConstraint("status IN ('active','disabled')", name="ck_demo_tenant_bindings_status"),
        CheckConstraint("(status = 'active' AND disabled_at IS NULL) OR (status = 'disabled' AND disabled_at IS NOT NULL)", name="ck_demo_tenant_bindings_disabled_state"),
        CheckConstraint("updated_at >= bound_at", name="ck_demo_tenant_bindings_updated_time"),
        CheckConstraint("disabled_at IS NULL OR disabled_at >= bound_at", name="ck_demo_tenant_bindings_disabled_time"),
        CheckConstraint("status <> 'disabled' OR updated_by_user_id IS NOT NULL", name="ck_demo_tenant_bindings_disabled_updater"),
    )

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", name="fk_demo_tenant_bindings_tenant", ondelete="RESTRICT"), primary_key=True)
    demo_tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    bound_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", name="fk_demo_tenant_bindings_bound_by", ondelete="RESTRICT"), nullable=False)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", name="fk_demo_tenant_bindings_updated_by", ondelete="RESTRICT"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))


class DemoTenantBindingHistory(Base):
    __tablename__ = "demo_tenant_binding_history"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_demo_tenant_binding_history"),
        UniqueConstraint("tenant_id", "binding_version", name="uq_demo_tenant_binding_history_tenant_version"),
        CheckConstraint("binding_version > 0", name="ck_demo_tenant_binding_history_version_positive"),
        CheckConstraint("operation IN ('create','disable','replace')", name="ck_demo_tenant_binding_history_operation"),
        CheckConstraint("(operation = 'create' AND binding_version = 1 AND before_snapshot IS NULL) OR (operation IN ('disable','replace') AND before_snapshot IS NOT NULL AND " + _snapshot_contract("before_snapshot") + " AND (before_snapshot->>'version')::integer = binding_version - 1)", name="ck_demo_tenant_binding_history_before"),
        CheckConstraint(_snapshot_contract("after_snapshot") + " AND (after_snapshot->>'version')::integer = binding_version", name="ck_demo_tenant_binding_history_after"),
        CheckConstraint("(after_snapshot->>'tenant_id')::bigint = tenant_id AND (after_snapshot->>'updated_by_user_id')::bigint = actor_user_id AND (before_snapshot IS NULL OR (before_snapshot->>'tenant_id')::bigint = tenant_id)", name="ck_demo_tenant_binding_history_links"),
        CheckConstraint("(operation = 'create' AND after_snapshot->>'status' = 'active' AND (after_snapshot->>'bound_by_user_id')::bigint = actor_user_id) OR (operation = 'replace' AND before_snapshot->>'status' IN ('active','disabled') AND after_snapshot->>'status' = 'active') OR (operation = 'disable' AND before_snapshot->>'status' = 'active' AND after_snapshot->>'status' = 'disabled')", name="ck_demo_tenant_binding_history_transition"),
        CheckConstraint("btrim(reason) <> ''", name="ck_demo_tenant_binding_history_reason"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", name="fk_demo_tenant_binding_history_tenant", ondelete="RESTRICT"), nullable=False)
    binding_version: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    before_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    after_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", name="fk_demo_tenant_binding_history_actor", ondelete="RESTRICT"), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

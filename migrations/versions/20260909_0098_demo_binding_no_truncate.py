"""Prevent physical truncation of the current demo binding table."""

from alembic import op


revision = "0098_demo_binding_no_truncate"
down_revision = "0097_demo_tenant_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TRIGGER trg_demo_tenant_bindings_no_truncate
        BEFORE TRUNCATE ON public.demo_tenant_bindings
        FOR EACH STATEMENT EXECUTE FUNCTION public.reject_demo_tenant_binding_delete()
    """)


def downgrade() -> None:
    raise RuntimeError(
        "0098_demo_binding_no_truncate is irreversible: retain binding deletion protection"
    )

"""GEO D0/D1: prompt taxonomy + CN media blueprint fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0045_geo_d0_d1"
down_revision = "0044_geo_fact_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_prompts",
        sa.Column("question_group", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "geo_prompts",
        sa.Column("market", sa.String(length=16), nullable=False, server_default="cn"),
    )
    op.add_column(
        "geo_prompts",
        sa.Column(
            "is_brand_probe",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_geo_prompts_tenant_probe",
        "geo_prompts",
        ["tenant_id", "is_brand_probe"],
    )
    op.create_index(
        "ix_geo_prompts_tenant_group",
        "geo_prompts",
        ["tenant_id", "question_group"],
    )

    op.add_column(
        "geo_media_placements",
        sa.Column("channel_key", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "geo_media_placements",
        sa.Column("priority_band", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "geo_media_placements",
        sa.Column("fits_groups", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "geo_media_placements",
        sa.Column("citation_national", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_geo_media_placements_tenant_channel_key",
        "geo_media_placements",
        ["tenant_id", "channel_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_geo_media_placements_tenant_channel_key",
        table_name="geo_media_placements",
    )
    op.drop_column("geo_media_placements", "citation_national")
    op.drop_column("geo_media_placements", "fits_groups")
    op.drop_column("geo_media_placements", "priority_band")
    op.drop_column("geo_media_placements", "channel_key")

    op.drop_index("ix_geo_prompts_tenant_group", table_name="geo_prompts")
    op.drop_index("ix_geo_prompts_tenant_probe", table_name="geo_prompts")
    op.drop_column("geo_prompts", "is_brand_probe")
    op.drop_column("geo_prompts", "market")
    op.drop_column("geo_prompts", "question_group")

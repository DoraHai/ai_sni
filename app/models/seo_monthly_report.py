"""Per-site PDF report section templates."""
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SeoSiteReportTemplate(Base):
    __tablename__ = "seo_site_report_templates"
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    sections: Mapped[list] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

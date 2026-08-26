from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DECIMAL, Date, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 服务商 OAuth 授权的百度推广账户唯一标识；一个推广账户对应一个客户。
    baidu_ucid: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    strategy: Mapped[str | None] = mapped_column(String(20))
    monthly_budget: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 2))
    contract_start: Mapped[date | None] = mapped_column(Date)
    contract_end: Mapped[date | None] = mapped_column(Date)
    # 品牌词根列表（如 ["苏尔寿"]），关键词分级识别品牌词用；不填回退用 name
    brand_terms: Mapped[list | None] = mapped_column(JSONB)
    # ===== 客户画像（迁移 0017）：行业/业务描述可编辑，喂 AI 调价建议 + 画像页 =====
    industry: Mapped[str | None] = mapped_column(String(100))  # 如「工业泵 / 分离技术」
    business_desc: Mapped[str | None] = mapped_column(Text)  # 业务/投放定位补充
    profile_summary: Mapped[str | None] = mapped_column(Text)  # AI 画像总结缓存
    profile_generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

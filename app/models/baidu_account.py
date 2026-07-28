from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BaiduAccount(Base):
    """百度推广账户授权信息。

    auth_mode:
      - self:  客户应用自授权（dev2.baidu.com 应用详情 - 自授权信息），90 天过期靠后台续期
      - oauth: OAuth 流程换取的 token（P1 实现），24 小时过期靠 refresh_token 自动刷新
    """

    __tablename__ = "baidu_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_username: Mapped[str] = mapped_column(String(100), nullable=False)
    baidu_ucid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    auth_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="self")
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

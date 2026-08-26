from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BaiduOAuthState(Base):
    """一次性 OAuth state。

    浏览器离开 SEM 前写入，百度回调时消费。数据库只保存 state 的 SHA-256，
    避免日志或数据库泄露后被直接重放。
    """

    __tablename__ = "baidu_oauth_states"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    return_path: Mapped[str] = mapped_column(
        String(300), nullable=False, default="/onboarding"
    )
    bind_to_tenant: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class BaiduOAuthGrant(Base):
    """一次百度 OAuth 授权主体及其 Token。

    一个超管/代理商授权可覆盖多个推广子账户；Token 只在这里保存一份主副本，
    baidu_accounts 中保留加密副本以兼容现有同步代码。
    """

    __tablename__ = "baidu_oauth_grants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False
    )
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    oauth_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    open_id: Mapped[str] = mapped_column(String(200), nullable=False)
    master_ucid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    master_name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[int] = mapped_column(nullable=False, default=1)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )
    authorized_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    """账号。角色由 role_id 指向 roles 表（自定义角色 RBAC，迁移 0016 起）。

    tenant_id = 限定该账号只能看某个客户（品牌方客户场景），独立于角色；NULL = 全客户可见。
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(50))
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id"), nullable=False)
    # 限定单客户（独立于角色）；NULL=全客户（顶栏可切换）
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.database import Base
from app import models  # noqa: F401  确保所有模型被注册到 Base.metadata
from migrations.session_timeouts import session_timeouts, verify_session_timeouts

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 注意：alembic 用 configparser 存 URL，% 会被当作变量插值符号。
# 我们的 DATABASE_URL 已经做过 URL 编码（密码里的特殊字符变成 %xx），
# 这里要再把 % 转义成 %% 才能塞进 configparser。
config.set_main_option(
    "sqlalchemy.url", get_settings().database_url.replace("%", "%%")
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    if session_timeouts(os.environ) is not None:
        raise ValueError("Session timeout overrides require an online asyncpg connection; offline SQL cannot verify them")
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection, timeouts=None) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        if timeouts is not None:
            # Keep this SELECT inside Alembic's transaction. Checking before
            # configure/begin would autobegin an unowned transaction and could
            # leave successful DDL rolled back when the connection closes.
            verify_session_timeouts(connection, timeouts)
        context.run_migrations()


async def run_async_migrations() -> None:
    timeouts = session_timeouts(os.environ)
    options = {}
    if timeouts is not None:
        if make_url(config.get_main_option("sqlalchemy.url")).drivername != "postgresql+asyncpg":
            raise ValueError("Session timeout overrides require postgresql+asyncpg")
        options["connect_args"] = {"server_settings": timeouts}
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        **options,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations, timeouts)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

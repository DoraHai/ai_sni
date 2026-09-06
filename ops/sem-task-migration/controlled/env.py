"""Dedicated reviewed transaction; never loads application configuration."""
from alembic import context

cfg = context.config
if context.is_offline_mode() or cfg.attributes.get("controlled_target") != "0095_sem_tasks":
    raise RuntimeError("Use the reviewed controlled entry")
context.configure(connection=cfg.attributes["connection"],
                  version_table_schema="public", transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()

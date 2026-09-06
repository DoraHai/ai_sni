"""Local-test-only migration environment; no application settings or URLs."""
from alembic import context

config = context.config
if not config.attributes.get("local_test_authorized") or context.is_offline_mode():
    raise RuntimeError("Only the guarded local test runner may load this environment")
connection = config.attributes["connection"]
schema = config.attributes["test_schema"]
context.configure(connection=connection, version_table_schema=schema, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()

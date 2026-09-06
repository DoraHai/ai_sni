"""Run GEO checks without live credentials; --postgres uses an empty CI database."""
import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare_environment():
    for key in list(os.environ):
        if key.endswith('_API_KEY'):
            os.environ[key] = ''
    os.environ.update(
        DATABASE_URL='postgresql+asyncpg://test:test@127.0.0.1:1/geo_test',
        APP_ENV='test', BAIDU_APP_ID='test', BAIDU_SECRET_KEY='test',
        BAIDU_DEFAULT_USERNAME='test', BAIDU_DEFAULT_UCID='0',
        BAIDU_SELF_ACCESS_TOKEN='test', BAIDU_SELF_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z',
        CRYPTO_MASTER_KEY_B64='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
        ADMIN_API_KEY='test-admin-key', JWT_SECRET='test-jwt-secret', TZ='UTC',
    )


def validate_ci_database(url):
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    if (parsed.drivername != 'postgresql+asyncpg'
            or parsed.host not in {'127.0.0.1', 'localhost'}
            or parsed.database != 'geo_ci' or parsed.username != 'geo_ci'
            or parsed.query):
        raise ValueError('PostgreSQL setup requires the dedicated loopback geo_ci database and user')


def create_fixture_tables(connection):
    from sqlalchemy import Column, MetaData, Table, inspect
    import app.models  # Register mapped columns; no application startup.
    from app.database import Base
    if inspect(connection).get_table_names():
        raise ValueError('CI fixture database must be empty; existing tables will not be modified')
    # Structure only. Test schemas own their data and do not reference other modules.
    names = ('tenants', 'geo_action_tickets', 'geo_content_tasks', 'geo_article_versions',
             'geo_channel_variants', 'geo_channel_accounts', 'geo_publishing_channels')
    metadata = MetaData()
    for name in names:
        source = Base.metadata.tables[name]
        Table(name, metadata, *(Column(c.name, c.type, nullable=c.nullable) for c in source.columns))
    metadata.create_all(connection)


async def initialize_postgres(url):
    from sqlalchemy.ext.asyncio import create_async_engine
    validate_ci_database(url)
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(create_fixture_tables)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres', action='store_true')
    args = parser.parse_args()
    postgres_url = os.environ.pop('GEO_TEST_POSTGRES_URL', None)
    prepare_environment()
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    from app.config import Settings
    Settings.model_config = {**Settings.model_config, 'env_file': None}
    if args.postgres:
        if not postgres_url:
            parser.error('--postgres requires GEO_TEST_POSTGRES_URL; database tests may not silently skip')
        asyncio.run(initialize_postgres(postgres_url))
        os.environ['GEO_TEST_POSTGRES_URL'] = postgres_url
    import pytest
    files = sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'tests').glob('test_geo*.py'))
    files += ['tests/test_metric_service.py', 'tests/test_md_to_html_tables.py', 'tests/test_channel_article_quality.py']
    return pytest.main(['-q', '--tb=short', *files])


if __name__ == '__main__':
    raise SystemExit(main())

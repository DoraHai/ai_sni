import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from ops.run_geo_checks import initialize_postgres, validate_ci_database, create_fixture_tables


@pytest.mark.parametrize('url', [
    'postgresql+asyncpg://geo_ci:dummy@db.example.com/geo_ci',
    'postgresql+asyncpg://admin:dummy@127.0.0.1/geo_ci',
    'postgresql+asyncpg://geo_ci:dummy@localhost/production',
    'postgresql+asyncpg://geo_ci:dummy@localhost/geo_ci?host=db.example.com',
    'sqlite:///geo_ci',
])
def test_ci_setup_rejects_non_fixture_database_before_connecting(url):
    with patch('sqlalchemy.ext.asyncio.create_async_engine') as connect:
        with pytest.raises(ValueError):
            asyncio.run(initialize_postgres(url))
        connect.assert_not_called()


def test_ci_accepts_dedicated_loopback_postgres():
    validate_ci_database('postgresql+asyncpg://geo_ci:dummy@127.0.0.1:5432/geo_ci')


def test_ci_never_overwrites_existing_tables():
    with patch('sqlalchemy.inspect', return_value=SimpleNamespace(get_table_names=lambda: ['existing'])), \
         patch('sqlalchemy.MetaData.create_all') as create:
        with pytest.raises(ValueError, match='must be empty'):
            create_fixture_tables(object())
        create.assert_not_called()

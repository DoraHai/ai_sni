"""Run the project-client regression set with synthetic settings, offline.

No dotenv/config files, server startup, customer identities or PostgreSQL
connections are needed. The endpoint tests use an in-memory SQLite fixture.
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    from app import config
    synthetic = config.Settings.model_construct(
        database_url='postgresql+asyncpg://offline@127.0.0.1/offline', app_env='test',
        admin_api_key='synthetic-offline-signing-value', baidu_app_id='synthetic',
        baidu_secret_key='synthetic', baidu_default_username='synthetic',
        baidu_default_ucid=0, baidu_self_access_token='synthetic',
        baidu_self_token_expires_at='2099-01-01T00:00:00Z',
        crypto_master_key_b64='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
    )
    config.get_server_settings = lambda: synthetic

    def deny_network(*args, **kwargs):
        raise AssertionError('External network/database forbidden in offline client checks')
    socket.create_connection = deny_network
    import asyncpg
    asyncpg.connect = deny_network
    import pytest
    default = [
        'tests/test_geo_project_client.py', 'tests/test_geo_read_model.py',
        'tests/test_geo_question_read_routes.py', 'tests/test_geo_acceptance_readiness.py',
        'tests/test_geo_read_entitlement.py', 'tests/test_geo_project_routes.py',
        'tests/test_geo_integration.py', 'tests/test_geo_onsite_core.py',
        'tests/test_geo_search_visibility.py', 'tests/test_geo_advisor_write_guard.py',
        'tests/test_geo_advisor_write_objects.py',
    ]
    return pytest.main(sys.argv[1:] or ['-q', *default])


if __name__ == '__main__':
    raise SystemExit(main())

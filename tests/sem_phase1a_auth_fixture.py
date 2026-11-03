"""Shared synthetic account authorization DB for phase1a API integration tests."""
import sqlite3
from contextlib import closing
from datetime import datetime

import pytest

from app.sem_phase1a.principals import LocalGrantPrincipalAdapter


@pytest.fixture
def auth_db(tmp_path):
    path = tmp_path / "synthetic-auth.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE tenants(id INTEGER PRIMARY KEY);
            INSERT INTO tenants VALUES(101),(102);
            CREATE TABLE users(id INTEGER PRIMARY KEY,is_active INTEGER,locked_until TEXT,tenant_id INTEGER,role TEXT);
            CREATE TABLE advisor_tenant_grants(id INTEGER PRIMARY KEY,user_id INTEGER,tenant_id INTEGER,revoked_at TEXT);
            CREATE TABLE tenant_modules(tenant_id INTEGER,module_code TEXT,status TEXT,expires_at TEXT);
            CREATE TABLE baidu_accounts(id INTEGER PRIMARY KEY,tenant_id INTEGER,status TEXT);
                CREATE TABLE sem_phase1a_account_grants(user_id INTEGER,tenant_id INTEGER,account_id INTEGER,
                    advisor_grant_id INTEGER,revoked_at TEXT);
                INSERT INTO sem_phase1a_account_grants VALUES(1,101,201,10,NULL),(2,101,201,NULL,NULL);
            INSERT INTO users VALUES(1,1,NULL,NULL,'advisor'),(2,1,NULL,101,'customer'),(3,1,NULL,102,'customer');
            INSERT INTO advisor_tenant_grants VALUES(10,1,101,NULL),(20,1,102,NULL);
            INSERT INTO sem_phase1a_account_grants VALUES(1,102,202,20,NULL);
            INSERT INTO tenant_modules VALUES(101,'sem','active',NULL),(102,'sem','trial',NULL);
            INSERT INTO baidu_accounts VALUES(201,101,'active'),(202,102,'active'),(203,101,'inactive');
        """)
    return path


def adapter(path):
    return LocalGrantPrincipalAdapter(path, clock=lambda: datetime.fromisoformat("2026-10-29T00:00:00+08:00"))

"""Exercise the existing Alembic entry with fake I/O, never load app credentials."""
import logging
import runpy
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from alembic import context
from alembic.config import Config
from sqlalchemy import MetaData
import sqlalchemy.ext.asyncio as sa_async

from migrations.session_timeouts import session_timeouts, verify_session_timeouts

LOCK = "ALEMBIC_LOCK_TIMEOUT_MS"
STATEMENT = "ALEMBIC_STATEMENT_TIMEOUT_MS"


def test_absent_overrides_preserve_default_driver_settings():
    assert session_timeouts({}) is None


@pytest.mark.parametrize("lock,statement", [("1","1"),("10000","300000"),(" 5000 ","300000")])
def test_explicit_limits(lock,statement):
    assert session_timeouts({LOCK:lock,STATEMENT:statement}) == {
        "lock_timeout":f"{int(lock)}ms", "statement_timeout":f"{int(statement)}ms"}


@pytest.mark.parametrize("values", [
    {LOCK:"5000"}, {STATEMENT:"300000"},
    {LOCK:"",STATEMENT:"300000"}, {LOCK:"0",STATEMENT:"300000"},
    {LOCK:"10001",STATEMENT:"300000"}, {LOCK:"5000",STATEMENT:"300001"},
    {LOCK:"5000",STATEMENT:"0"}, {LOCK:"-1",STATEMENT:"300000"},
    {LOCK:"5s",STATEMENT:"300000"}, {LOCK:"5000.0",STATEMENT:"300000"},
    {LOCK:"5000",STATEMENT:"1; DROP TABLE x"},
])
def test_invalid_or_partial_overrides_stop(values):
    with pytest.raises(ValueError): session_timeouts(values)


def run_entry(monkeypatch, *, enabled=True, mismatch=False, offline=False, driver="postgresql+asyncpg", fail_ddl=False):
    events, captured = [], {}
    for key in (LOCK,STATEMENT): monkeypatch.delenv(key,raising=False)
    if enabled:
        monkeypatch.setenv(LOCK,"5000"); monkeypatch.setenv(STATEMENT,"300000")
    # Run env.py itself, with only its application config/DB metadata imports
    # replaced. No .env, identities file, driver socket or real DDL is touched.
    app = ModuleType("app"); app.__path__ = []
    config_mod = ModuleType("app.config")
    config_mod.get_settings = lambda: SimpleNamespace(database_url=f"{driver}://test@localhost/not_connected")
    database = ModuleType("app.database"); database.Base = SimpleNamespace(metadata=MetaData())
    models = ModuleType("app.models"); app.models = models
    for name,module in {"app":app,"app.config":config_mod,"app.database":database,"app.models":models}.items():
        monkeypatch.setitem(sys.modules,name,module)
    monkeypatch.setattr(context,"config",Config(),raising=False)
    monkeypatch.setattr(context,"is_offline_mode",lambda:offline)
    monkeypatch.setattr(context,"configure",lambda **kw:events.append("configure"))
    @contextmanager
    def transaction():
        events.append("begin")
        try: yield
        except Exception:
            events.append("rollback"); raise
        else: events.append("commit")
    monkeypatch.setattr(context,"begin_transaction",transaction)
    def ddl():
        events.append("DDL")
        if fail_ddl: raise RuntimeError("synthetic DDL failure")
    monkeypatch.setattr(context,"run_migrations",ddl)
    class SyncConnection:
        def execute(self,sql):
            assert events[-1] == "begin", "timeout SELECT must not autobegin before Alembic owns transaction"
            assert "pg_catalog.pg_settings" in str(sql)
            events.append("verify")
            return SimpleNamespace(mappings=lambda:[
                {"name":"lock_timeout","setting":"0" if mismatch else "5000","unit":"ms"},
                {"name":"statement_timeout","setting":"300000","unit":"ms"}])
    class AsyncConnection:
        async def __aenter__(self): events.append("connect"); return self
        async def __aexit__(self,*exc): events.append("close")
        async def run_sync(self,fn,*args): return fn(SyncConnection(),*args)
    class Engine:
        def connect(self): return AsyncConnection()
        async def dispose(self): events.append("dispose")
    def factory(section,**kwargs):
        captured.update(kwargs); return Engine()
    monkeypatch.setattr(sa_async,"async_engine_from_config",factory)
    error = None
    try:
        runpy.run_path(str(Path(__file__).parents[1]/"migrations/env.py"))
    except (ValueError,RuntimeError) as exc:
        error = exc
    return events,captured,error


def test_online_passes_server_settings_checks_before_ddl_and_commits(monkeypatch,caplog):
    with caplog.at_level(logging.INFO,logger="alembic.runtime.migration"):
        events,args,error=run_entry(monkeypatch)
    assert error is None
    assert args["connect_args"] == {"server_settings":{"lock_timeout":"5000ms","statement_timeout":"300000ms"}}
    assert events == ["connect","configure","begin","verify","DDL","commit","close","dispose"]
    assert "lock_timeout_ms=5000 statement_timeout_ms=300000" in caplog.text
    assert "not_connected" not in caplog.text and "test@" not in caplog.text


def test_default_online_does_not_pass_args_or_run_timeout_query(monkeypatch):
    events,args,error=run_entry(monkeypatch,enabled=False)
    assert error is None and "connect_args" not in args and "verify" not in events
    assert events == ["connect","configure","begin","DDL","commit","close","dispose"]


def test_effective_mismatch_prevents_ddl_and_disposes(monkeypatch):
    events,args,error=run_entry(monkeypatch,mismatch=True)
    assert isinstance(error,RuntimeError) and "DDL" not in events and "commit" not in events
    assert events[-3:] == ["rollback","close","dispose"]


def test_ddl_failure_uses_existing_transaction_and_disposes(monkeypatch):
    events,args,error=run_entry(monkeypatch,fail_ddl=True)
    assert isinstance(error,RuntimeError) and "DDL" in events and "commit" not in events
    assert events[-3:] == ["rollback","close","dispose"]


@pytest.mark.parametrize("offline,driver", [(True,"postgresql+asyncpg"),(False,"postgresql+psycopg2")])
def test_explicit_override_cannot_silently_use_unverified_mode(monkeypatch,offline,driver):
    events,args,error=run_entry(monkeypatch,offline=offline,driver=driver)
    assert isinstance(error,ValueError) and not args and not events


def test_offline_default_preserves_existing_behavior(monkeypatch):
    events,args,error=run_entry(monkeypatch,enabled=False,offline=True)
    assert error is None and events == ["configure","begin","DDL","commit"] and not args


@pytest.mark.parametrize("found", [[],[
    {"name":"lock_timeout","setting":"5000","unit":"s"},
    {"name":"statement_timeout","setting":"300000","unit":"ms"}]])
def test_missing_setting_or_unexpected_unit_stops(found):
    connection=SimpleNamespace(execute=lambda sql:SimpleNamespace(mappings=lambda:found))
    with pytest.raises(RuntimeError):
        verify_session_timeouts(connection,{"lock_timeout":"5000ms","statement_timeout":"300000ms"})

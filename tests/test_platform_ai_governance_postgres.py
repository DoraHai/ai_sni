"""Native PostgreSQL verification for the AI governance aggregation SQL."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app import ai_governance as governance


def _settings():
    return SimpleNamespace(
        dashscope_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        dashscope_model="qwen3.8-max",
        dashscope_api_key="configured-without-exposure",
        deepseek_base_url="https://api.deepseek.com/v1",
        deepseek_model="deepseek-chat",
        deepseek_api_key="",
        baidu_write_dry_run=True,
    )


def test_native_postgres_governance_sql_and_missing_controls(monkeypatch):
    raw = os.getenv("PLATFORM_CONSOLE_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("PLATFORM_CONSOLE_TEST_DATABASE_URL is required")
    url = make_url(raw)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"127.0.0.1", "localhost"}
    assert "test" in url.database.lower()
    schema = "ai_governance_" + uuid4().hex
    now = datetime.now(timezone.utc)

    async def run():
        setup = create_async_engine(raw)
        scoped = create_async_engine(raw, connect_args={"server_settings": {"search_path": schema}})
        try:
            async with setup.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with scoped.connect() as connection:
                native = await connection.get_raw_connection()
                ddl = (Path(__file__).parents[1] / "scripts" / "api_metering_schema.sql").read_text(encoding="utf-8")
                await native.driver_connection.execute(ddl)
                await connection.commit()
            async with scoped.begin() as connection:
                await connection.execute(text("""
                    INSERT INTO api_usage_events
                    (id,tenant_id,user_id,origin,module,operation,job_ref,provider,model,endpoint,state,
                     currency,estimated_amount,started_at)
                    VALUES
                    (CAST(:sem_id AS uuid),1,10,'interactive','sem','chat.completions','task:1',
                     'dashscope.aliyuncs.com','qwen3.8-max','dashscope.aliyuncs.com/chat/completions',
                     'succeeded','CNY',1.25,:recent),
                    (CAST(:seo_error_id AS uuid),2,20,'interactive','seo','onsite.ai_proposal','site:2',
                     'dashscope.aliyuncs.com','qwen3.8-max','dashscope.aliyuncs.com/chat/completions',
                     'error',NULL,NULL,:recent),
                    (CAST(:seo_unknown_id AS uuid),2,NULL,'job','seo','onsite.ai_proposal','site:2',
                     'dashscope.aliyuncs.com','qwen3.8-max','dashscope.aliyuncs.com/chat/completions',
                     'unknown',NULL,NULL,:recent),
                    (CAST(:seo_requested_id AS uuid),2,NULL,'job','seo','onsite.ai_proposal','site:2',
                     'dashscope.aliyuncs.com','qwen3.8-max','dashscope.aliyuncs.com/chat/completions',
                     'requested',NULL,NULL,:recent),
                    (CAST(:geo_old_id AS uuid),3,30,'interactive','geo','onsite.ai_proposal','project:3',
                     'dashscope.aliyuncs.com','qwen3.8-max','dashscope.aliyuncs.com/chat/completions',
                     'succeeded','CNY',2.50,:old)
                """), {
                    "sem_id": str(uuid4()), "seo_error_id": str(uuid4()),
                    "seo_unknown_id": str(uuid4()), "seo_requested_id": str(uuid4()),
                    "geo_old_id": str(uuid4()), "recent": now - timedelta(minutes=5),
                    "old": now - timedelta(hours=48),
                })
            monkeypatch.setattr(governance.api_metering, "enabled", lambda: True)
            monkeypatch.setattr(governance.api_controls, "enabled", lambda: False)
            async with scoped.connect() as connection:
                result = await governance.read_ai_governance(connection, now=now, settings=_settings())

            modules = {item["module"]: item for item in result["modules"]}
            assert result["state"] == "available"
            assert result["controls"] == {
                "schema": "schema_pending", "enabled": False, "editing": "disabled",
                "note": "控制结构未经人工审核或未启用时仅提供只读计量，不开放编辑。",
            }
            assert modules["sem"]["calls"]["total"] == 1
            assert modules["sem"]["calls"]["known_amount"] == "1.250000000000"
            assert modules["sem"]["calls"]["estimated_amount"] == "1.250000000000"
            assert modules["seo"]["calls"]["total"] == 3
            assert modules["seo"]["calls"]["failed"] == 1
            assert modules["seo"]["calls"]["unknown"] == 1
            assert modules["seo"]["calls"]["pending"] == 1
            assert modules["seo"]["calls"]["unpriced"] == 3
            assert modules["seo"]["calls"]["estimated_amount"] is None
            assert modules["seo"]["calls"]["features"][0]["feature"] == "onsite.ai_proposal"
            # GEO has a real ledger event outside the declared 24-hour window;
            # the window aggregate is therefore a proven zero, not unknown.
            assert modules["geo"]["calls"]["total"] == 0
            assert modules["geo"]["calls"]["known_amount"] == "0"
            assert modules["geo"]["calls"]["estimated_amount"] == "0"
        finally:
            await scoped.dispose()
            async with setup.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await setup.dispose()

    asyncio.run(run())

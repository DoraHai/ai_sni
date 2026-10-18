import asyncio
import json
import logging
from unittest.mock import AsyncMock

import pytest
from app.models import GeoArticleVersion, GeoChannelVariant, GeoContentTask, GeoProject
from app.geo.content.export_view import export_revision
from test_advisor_scoped_writes import write_sandbox, mutate


def test_advisor_exports_current_variant_and_records(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="geo.advisor.operations")
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            async with env.factory() as session:
                variant = await session.get(GeoChannelVariant, 10)
                revision = export_revision(variant, 10)
            response = await env.request("POST", "/content-tasks/10/export",
                body={"expected_revision": revision}, params={"channel": "website"})
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                assert (await session.get(GeoChannelVariant, 10)).status == "exported"
    asyncio.run(run())
    assert any(json.loads(r.message)["result"] == "committed" for r in caplog.records
               if r.name == "geo.advisor.operations")


@pytest.mark.parametrize("action", ["export", "publications", "push", "push-batch", "variants"])
@pytest.mark.parametrize("failure", ["unselected", "inactive", "disabled"])
def test_publication_operations_stay_scoped(tmp_path, monkeypatch, action, failure):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, enabled=failure != "disabled") as env:
            params = {}
            if failure == "inactive":
                await mutate(env, GeoProject, 10, status="paused")
            if failure == "unselected":
                params["tenant_id"] = 20
            response = await env.request("POST", "/content-tasks/10/" + action, body={}, params=params)
            assert response.status_code == 403, response.text
    asyncio.run(run())


def test_actor_rechecked_before_each_external_attempt():
    from types import SimpleNamespace
    from app.security.advisor_write_publish import recheck_external
    from fastapi import HTTPException
    from unittest.mock import patch
    session = SimpleNamespace(info={"advisor_scoped_write": (object(), SimpleNamespace(scope={}))})
    check = AsyncMock(side_effect=HTTPException(403, "revoked"))
    with patch("app.security.advisor_write_commit.recheck_advisor_before_commit", check):
        with pytest.raises(HTTPException):
            asyncio.run(recheck_external(session, "external_attempt"))
    assert check.await_count == 1

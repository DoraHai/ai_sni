import asyncio
import json
import logging

import pytest
from app.models import GeoContentTask
from test_advisor_scoped_writes import write_sandbox, mutate


@pytest.mark.parametrize("action", ["submit-review", "review"])
def test_proxy_review_keeps_version_and_advisor_evidence(tmp_path, monkeypatch, caplog, action):
    caplog.set_level(logging.INFO, logger="geo.advisor.operations")
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            await mutate(env, GeoContentTask, 10, review_status="none" if action == "submit-review" else "pending")
            async with env.factory() as session:
                stamp = (await session.get(GeoContentTask, 10)).updated_at.isoformat()
            body = {"expected_article_id": 10, "expected_updated_at": stamp, "note": "微信确认"}
            if action == "review":
                body["decision"] = "approved"
            response = await env.request("POST", "/content-tasks/10/" + action, body=body)
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                task = await session.get(GeoContentTask, 10)
                evidence = task.rule_result["advisor_review_evidence"]
                assert evidence["article_id"] == 10 and evidence["advisor_user_id"] == 1
                assert len(evidence["content_sha256"]) == 64 and evidence["agreement_note"] == "微信确认"
                assert task.review_status == ("pending" if action == "submit-review" else "approved")
    asyncio.run(run())
    assert any(json.loads(r.message).get("review", {}).get("article_id") == 10
               for r in caplog.records if r.name == "geo.advisor.operations")


@pytest.mark.parametrize("failure", ["missing-version", "stale", "other-customer", "disabled"])
def test_proxy_review_rejects_wrong_scope_or_version(tmp_path, monkeypatch, failure):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, enabled=failure != "disabled") as env:
            await mutate(env, GeoContentTask, 10, review_status="pending")
            async with env.factory() as session:
                stamp = (await session.get(GeoContentTask, 10)).updated_at.isoformat()
            body = {"expected_article_id": 10, "expected_updated_at": stamp, "decision": "approved"}
            if failure == "missing-version":
                body.pop("expected_article_id")
            elif failure == "stale":
                body["expected_updated_at"] = "2000-01-01"
            elif failure == "other-customer":
                body["expected_article_id"] = 20
            response = await env.request("POST", "/content-tasks/10/review", body=body)
            assert response.status_code in {400, 403, 409}, response.text
            async with env.factory() as session:
                assert (await session.get(GeoContentTask, 10)).review_status == "pending"
    asyncio.run(run())

"""GEO 内容发布门禁。"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.geo.content.ai_reviewer import reviewer_blocks_publish
from app.geo.content.geo_score import score_blocks_ready
from app.geo.content.review import assert_review_approved
from app.geo.content.rules import RuleInput, is_ready, run_checks


class PublishGateError(ValueError):
    pass


def assert_can_publish(
    rule_input: RuleInput,
    *,
    task: Any | None = None,
) -> list:
    checks = run_checks(rule_input)
    if not is_ready(checks, require_channels=True):
        failed = [c.code for c in checks if not c.passed]
        raise PublishGateError("未达发布就绪: " + ", ".join(failed))
    if task is not None:
        try:
            assert_review_approved(task)
        except ValueError as exc:
            raise PublishGateError(str(exc)) from exc
        # P2 / P3 optional gates from last check / review payload
        settings = get_settings()
        rr = getattr(task, "rule_result", None) or {}
        if not isinstance(rr, dict):
            rr = {}
        score_payload = {
            "geo_score": rr.get("geo_score"),
            "geo_subscores": rr.get("geo_subscores"),
        }
        ok_score, msg_score = score_blocks_ready(
            score_payload,
            threshold=int(getattr(settings, "geo_score_threshold", 60) or 60),
            gate_enabled=bool(getattr(settings, "geo_score_gate", False)),
        )
        if not ok_score:
            raise PublishGateError(msg_score)
        ok_rev, msg_rev = reviewer_blocks_publish(
            rr.get("ai_review") if isinstance(rr.get("ai_review"), dict) else None,
            gate_enabled=bool(getattr(settings, "geo_ai_review_gate", False)),
        )
        if not ok_rev:
            raise PublishGateError(msg_rev)
    return checks

"""GEO 内容发布门禁。"""

from __future__ import annotations

from app.geo.content.rules import RuleInput, is_ready, run_checks


class PublishGateError(ValueError):
    pass


def assert_can_publish(rule_input: RuleInput) -> list:
    checks = run_checks(rule_input)
    if not is_ready(checks, require_channels=True):
        failed = [c.code for c in checks if not c.passed]
        raise PublishGateError("未达发布就绪: " + ", ".join(failed))
    return checks

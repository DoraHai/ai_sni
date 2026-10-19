"""Version-bound proxy customer decisions on existing JSON/log storage."""
from datetime import datetime, timezone
import hashlib
import json

from fastapi import HTTPException


def record_review(session, ctx, task, article, req, action):
    if getattr(ctx, "advisor_scope", None) is None:
        return
    if (article is None or req.expected_article_id is None
            or not req.expected_updated_at):
        raise HTTPException(400, "请先刷新稿件，再提交当前版本的审核操作")
    if req.expected_article_id != article.id or req.expected_updated_at != task.updated_at.isoformat():
        raise HTTPException(409, "稿件或渠道稿已有变化，请刷新后重新确认")
    binding = session.info.get("advisor_scoped_write")
    if binding is None or binding[0] is not ctx:
        raise HTTPException(403, "缺少顾问审核授权范围")
    digest = hashlib.sha256(json.dumps({"title": article.title, "body_markdown": article.body_markdown},
                            ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    evidence = {"advisor_user_id": ctx.user_id, "tenant_id": ctx.tenant_id,
                "article_id": article.id, "article_version": article.version_no,
                "content_sha256": digest, "action": action,
                "agreement_note": (req.note or "").strip() or None,
                "time": datetime.now(timezone.utc).isoformat()}
    task.rule_result = {**(task.rule_result or {}), "advisor_review_evidence": evidence}
    binding[1].scope["geo_advisor_review"] = evidence

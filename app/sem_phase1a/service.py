"""仅进程内合成演练服务；显式phase0存储与可信权限注入，无配置/环境/生产库依赖。"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from app.sem_phase0.contracts import LandingSubmission
from app.sem_phase0.store import RevisionConflict, SubmissionStore, check_scope
from app.sem_phase1a.contracts import PlanRow, WARNING
from app.sem_phase1a.planning import checks, duplicates, expiry_suggestions, generate
from app.sem_phase1a.sources import FIXTURES, collect, comparisons


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


class ShadowService:
    def __init__(self, submissions: SubmissionStore):
        self.submissions = submissions
        self._plans = {}
        self._previews = {}
        self._lock = RLock()
        self._fixtures = json.loads((FIXTURES / "existing.internal.json").read_text(encoding="utf-8"))

    def _audit(self, state, principal, action, details):
        event = {"ordinal": len(state["audit"])+1, "actor": principal.actor_id,
                 "at": datetime.now(timezone.utc).isoformat(), "action": action,
                 "version": state["version"], "details": details,
                 "previous_sha256": state["audit"][-1]["sha256"] if state["audit"] else None}
        state["audit"].append({**event, "sha256": digest(event)})

    def _state(self, principal, plan_id, expected=None):
        state = self._plans.get(plan_id)
        if state is None:
            raise KeyError("无该演练规划")
        payload = LandingSubmission.model_validate(state["submission"])
        check_scope(principal, payload.tenant_id, payload.account_id)
        if expected is not None and state["version"] != expected:
            raise RevisionConflict("演练版本过期，请重新读取")
        if self.submissions.read(principal, payload.tenant_id, payload.account_id,
                                 payload.landing_page_id, state["submission_revision"] + 1):
            raise RevisionConflict("阶段0已有新来源版本，请重新创建演练规划，旧批准失效")
        return state

    def create(self, principal, request):
        from app.sem_phase1a.contracts import CreateRequest

        request = CreateRequest.model_validate(request.model_dump())
        check_scope(principal, request.tenant_id, request.account_id)
        submission = self.submissions.read(principal, request.tenant_id, request.account_id,
                                           request.page_id, request.submission_revision)
        if submission is None:
            raise KeyError("阶段0提交不存在")
        payload = LandingSubmission.model_validate(submission["payload"])
        if digest(submission["payload"]) != submission["payload_sha256"]:
            raise ValueError("阶段0来源hash不一致")
        account = next((a for a in self._fixtures["accounts"]
                        if (a["tenant_id"], a["account_id"]) == (request.tenant_id, request.account_id)), None)
        if account is None:
            raise ValueError("本刀仅允许已声明的合成账户夹具")
        sources = collect(payload, request.submission_revision, submission["payload_sha256"], request.fixture_id)
        with self._lock:
            state = {"plan_id": uuid4().hex, "version": 1, "submission": submission["payload"],
                     "submission_revision": request.submission_revision,
                     "submission_sha256": submission["payload_sha256"],
                     "sources": [s.model_dump() for s in sources], "comparisons": comparisons(sources),
                     "selected": {}, "rows": [], "approvals": {}, "audit": [], "history": [],
                     "rulings": [], "synthetic": True, "backend": "fixture", "generator": "deterministic_rules",
                     "warning": WARNING, "mode": "rehearsal", "customer_confirmation": "pending",
                     "execution_export_enabled": False, "enable_allowed": False,
                     "existing_assets": copy.deepcopy(account["assets"]), "budget_cap_cents": account["budget_cap_cents"]}
            # 新创建也拒绝过期的阶段0版本。
            if self.submissions.read(principal, request.tenant_id, request.account_id,
                                     request.page_id, request.submission_revision+1):
                raise RevisionConflict("阶段0版本过期")
            self._audit(state, principal, "created", {"submission_sha256": state["submission_sha256"]})
            self._plans[state["plan_id"]] = state
            return self._view(state)

    def _view(self, state):
        result = copy.deepcopy(state)
        rows = [PlanRow.model_validate(r) for r in result["rows"]]
        if rows:
            from app.sem_phase1a.contracts import Source

            result["p5"] = duplicates(rows, result["existing_assets"])
            result["p6"] = checks(rows, [Source.model_validate(s) for s in result["sources"]], result["budget_cap_cents"])
            result["advisor_review_complete"] = all(r.row_id in result["approvals"] for r in rows)
            result["plan_sha256"] = digest({"version": result["version"], "rows": result["rows"],
                                             "selected": result["selected"], "submission_sha256": result["submission_sha256"]})
        else:
            result["p5"] = {"passed": False, "issues": [{"rule": "not_generated", "blocking": True}]}
            result["p6"] = {"passed": False, "issues": [{"rule": "unresolved_sources", "blocking": True}]}
            result["advisor_review_complete"] = False
            result["plan_sha256"] = None
        result["state"] = "shadow_review" if rows else "awaiting_ruling"
        return result

    def read(self, principal, plan_id):
        with self._lock:
            return self._view(self._state(principal, plan_id))

    def rule(self, principal, plan_id, request):
        from app.sem_phase1a.contracts import RulingRequest, Source

        request = RulingRequest.model_validate(request.model_dump())
        with self._lock:
            state = self._state(principal, plan_id, request.expected_version)
            selected = {c["field"]: c["default_source_id"] for c in state["comparisons"]}
            by_id = {s["source_id"]: s for s in state["sources"]}
            for field, source_id in request.choices.items():
                if field not in selected or source_id not in by_id or by_id[source_id]["field"] != field:
                    raise ValueError("裁定只能选择该字段的已记录来源")
                selected[field] = source_id
            rows = [r.model_dump() for r in generate(LandingSubmission.model_validate(state["submission"]),
                    [Source.model_validate(s) for s in state["sources"]], selected)]
            self._archive(state)
            state["selected"] = selected
            state["rows"] = rows
            state["rulings"].append({"version": state["version"], "actor": principal.actor_id,
                                     "selected": copy.deepcopy(selected), "reason": request.reason})
            self._audit(state, principal, "sources_adjudicated_and_generated",
                        {"selected": selected, "reason": request.reason})
            return self._view(state)

    def _archive(self, state):
        state["history"].append({"version": state["version"], "rows": copy.deepcopy(state["rows"]),
                                 "selected": copy.deepcopy(state["selected"]),
                                 "approvals": copy.deepcopy(state["approvals"])})
        state["version"] += 1
        state["approvals"] = {}

    def preview(self, principal, plan_id, data, audience):
        from app.sem_phase1a.excel import parse_workbook

        with self._lock:
            state = self._state(principal, plan_id)
            view = self._view(state)
            parsed = parse_workbook(data, view, audience)
            changed = []
            for old, new in zip(state["rows"], parsed):
                for field in ("text", "budget_cents"):
                    if old[field] != new[field]:
                        changed.append({"row_id": old["row_id"], "field": field,
                                        "before": old[field], "after": new[field]})
            preview_id = uuid4().hex
            proposed = copy.deepcopy(state)
            proposed["rows"] = parsed
            proposed["approvals"] = {}
            report = self._view(proposed)
            preview = {"preview_id": preview_id, "plan_id": plan_id, "base_version": state["version"],
                       "audience": audience, "changes": changed, "p5": report["p5"], "p6": report["p6"],
                       "rehearsal_only": True, "customer_confirmation": "pending", "applied": False}
            self._previews[preview_id] = {"preview": preview, "rows": parsed}
            self._audit(state, principal, "excel_preview_only", {"preview_id": preview_id, "audience": audience,
                                                                 "changes": changed, "file_sha256": hashlib.sha256(data).hexdigest()})
            return copy.deepcopy(preview)

    def apply(self, principal, plan_id, request):
        from app.sem_phase1a.contracts import ApplyRequest

        request = ApplyRequest.model_validate(request.model_dump())
        with self._lock:
            state = self._state(principal, plan_id, request.expected_version)
            pending = self._previews.get(request.preview_id)
            if pending is None or pending["preview"]["plan_id"] != plan_id:
                raise ValueError("无该规划的预览")
            preview = pending["preview"]
            if preview["audience"] != "advisor":
                raise ValueError("客户演练差异只预览，不导入正式确认链")
            if preview["applied"] or preview["base_version"] != state["version"]:
                raise RevisionConflict("预览已应用或版本已过期")
            self._archive(state)
            state["rows"] = copy.deepcopy(pending["rows"])
            preview["applied"] = True
            self._audit(state, principal, "advisor_preview_applied", {"preview_id": request.preview_id})
            return self._view(state)

    def approve(self, principal, plan_id, request):
        from app.sem_phase1a.contracts import ApprovalRequest

        request = ApprovalRequest.model_validate(request.model_dump())
        with self._lock:
            state = self._state(principal, plan_id, request.expected_version)
            view = self._view(state)
            if not view["p5"]["passed"]:
                raise ValueError("精确重复硬阻断，先修改并重查")
            if any(i["rule"] in {"budget_tree", "account_cap", "negative_overlap", "text_length", "declared_boundary"}
                   for i in view["p6"]["issues"]):
                raise ValueError("存在可修订的硬检查问题，先修改并重查")
            if not state["rows"] or len(set(request.row_ids)) != len(request.row_ids):
                raise ValueError("逐项批准列表为空或重复")
            ids = {r["row_id"] for r in state["rows"]}
            if not set(request.row_ids) <= ids:
                raise ValueError("批准行不存在")
            for row_id in request.row_ids:
                state["approvals"][row_id] = {"actor": principal.actor_id, "reason": request.reason,
                    "version": state["version"], "plan_sha256": view["plan_sha256"], "internal_rehearsal_only": True}
            self._audit(state, principal, "rows_reviewed_internal_only", {"row_ids": request.row_ids, "reason": request.reason})
            return self._view(state)

    def export(self, principal, plan_id, audience):
        from app.sem_phase1a.excel import write_workbook

        with self._lock:
            state = self._state(principal, plan_id)
            view = self._view(state)
            if not view["rows"]:
                raise ValueError("先完成来源裁定")
            if audience == "customer" and not view["advisor_review_complete"]:
                raise ValueError("客户演练样例须先完成顾问逐项复核")
            data = write_workbook(view, audience)
            self._audit(state, principal, "excel_exported_internal_only", {"audience": audience,
                                                                          "file_sha256": hashlib.sha256(data).hexdigest()})
            return data

    def expiry(self, principal, plan_id, now):
        with self._lock:
            state = self._state(principal, plan_id)
            if not state["rows"]:
                raise ValueError("先生成影子规划")
            return expiry_suggestions(LandingSubmission.model_validate(state["submission"]),
                                      [PlanRow.model_validate(r) for r in state["rows"]], now)


def export_execution(*args, **kwargs):
    raise PermissionError("P9及以后硬关闭：无正式上传文件、无启用")


def enable_plan(*args, **kwargs):
    raise PermissionError("P9及以后硬关闭：无正式上传文件、无启用")

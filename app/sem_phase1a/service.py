"""可注入来源/规划存储的影子演练服务；真实来源只用顾问提交内容，执行保持关闭。"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
import time
from uuid import uuid4

from app.sem_phase0.contracts import LandingSubmission
from app.sem_phase0.store import RevisionConflict, SubmissionRepository, check_scope
from app.sem_phase1a.contracts import PlanRow, WARNING
from app.sem_phase1a.planning import checks, duplicates, expiry_suggestions, generate_bundle
from app.sem_phase1a.store import SQLiteShadowStore, ShadowStore
from app.sem_phase1a.errors import ShadowError
from app.sem_phase1a.sources import FIXTURES, collect, comparisons


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


class ShadowService:
    def list_plans(self, principal, tenant, account, offset=0, limit=50):
        check_scope(principal, tenant, account, write=False)
        states = self.store.list_plans(tenant, account, offset, limit)
        # Metadata only. Detail/Excel still revalidate all source bytes and hashes.
        return [{'plan_id': s['plan_id'], 'version': s['version'],
                 'pages': [{'page_id': e['payload']['landing_page_id'], 'revision': e['revision']}
                           for e in s['submissions']],
                 'product_line_id': s['submission']['product_line_id'],
                 'validation': 'detail_required', 'execution_enabled': False} for s in states]

    def __init__(self, submissions: SubmissionRepository, store: ShadowStore | None = None,
                 *, clock=time.time, preview_ttl=3600, submitted_only=False):
        self.submissions = submissions
        self.store = store if store is not None else SQLiteShadowStore(
            submissions.path.with_name(submissions.path.stem + ".shadow.sqlite3"))
        if preview_ttl <= 0:
            raise ValueError("预览TTL必须为正")
        self.clock, self.preview_ttl = clock, preview_ttl
        self.submitted_only = submitted_only
        self._fixtures = ({"accounts": []} if submitted_only else
                          json.loads((FIXTURES / "existing.internal.json").read_text(encoding="utf-8")))

    def _audit(self, state, principal, action, details):
        event = {"ordinal": len(state["audit"])+1, "actor": principal.actor_id,
                 "at": datetime.now(timezone.utc).isoformat(), "action": action,
                 "version": state["version"], "details": details,
                 "previous_sha256": state["audit"][-1]["sha256"] if state["audit"] else None}
        state["audit"].append({**event, "sha256": digest(event)})

    def _state(self, tx, principal, plan_id, expected=None, *, write=True):
        state = tx.plans.get(plan_id)
        if state is None:
            raise KeyError("无该演练规划")
        payload = LandingSubmission.model_validate(state["submission"])
        check_scope(principal, payload.tenant_id, payload.account_id, write=write)
        if expected is not None and state["version"] != expected:
            raise RevisionConflict("演练版本过期，请重新读取")
        for entry in state["submissions"]:
            item = LandingSubmission.model_validate(entry["payload"])
            if (item.tenant_id, item.account_id) != (payload.tenant_id, payload.account_id):
                raise ShadowError("SOURCE_INVALID", "来源账户校验失败")
            if digest(entry["payload"]) != entry["sha256"]:
                raise ShadowError("SOURCE_INVALID", "来源hash校验失败")
            current = self.submissions.read(principal, item.tenant_id, item.account_id,
                                            item.landing_page_id, entry["revision"])
            if current is None or current["payload_sha256"] != entry["sha256"]:
                raise RevisionConflict("阶段0来源已变更")
            if self.submissions.read(principal, item.tenant_id, item.account_id,
                                     item.landing_page_id, entry["revision"] + 1):
                raise RevisionConflict("阶段0已有新来源版本，请重新创建演练规划，旧批准失效")
        return state

    def create(self, principal, request):
        from app.sem_phase1a.contracts import BatchCreateRequest, CreateRequest, PageReference

        if isinstance(request, BatchCreateRequest):
            request = BatchCreateRequest.model_validate(request.model_dump())
            pages = request.pages
        else:
            request = CreateRequest.model_validate(request.model_dump())
            pages = [PageReference(page_id=request.page_id, submission_revision=request.submission_revision,
                                   fixture_id=request.fixture_id)]
        check_scope(principal, request.tenant_id, request.account_id)
        account = next((a for a in self._fixtures["accounts"]
                        if (a["tenant_id"], a["account_id"]) == (request.tenant_id, request.account_id)), None)
        if account is None and not self.submitted_only:
            raise ShadowError("SYNTHETIC_ACCOUNT_REQUIRED", "本刀仅允许已声明的合成账户夹具")
        entries, sources = [], []
        for index, page in enumerate(pages, 1):
            submission = self.submissions.read(principal, request.tenant_id, request.account_id,
                                               page.page_id, page.submission_revision)
            if submission is None:
                raise KeyError("阶段0提交不存在")
            payload = LandingSubmission.model_validate(submission["payload"])
            if digest(submission["payload"]) != submission["payload_sha256"]:
                raise ShadowError("SOURCE_INVALID", "阶段0来源hash不一致")
            prefix = f"p{index}:" if len(pages) > 1 else ""
            collected = collect(payload, page.submission_revision, submission["payload_sha256"], page.fixture_id,
                                submitted_only=self.submitted_only)
            sources.extend([source.model_copy(update={"source_id": f"p{index}-{source.source_id}",
                            "field": prefix + source.field}) if prefix else source for source in collected])
            entries.append({"payload": submission["payload"], "revision": page.submission_revision,
                            "sha256": submission["payload_sha256"], "prefix": prefix})
        if len({(e["payload"]["budget_period"], e["payload"]["currency"]) for e in entries}) != 1:
            raise ShadowError("BUDGET_INVALID", "多页预算周期/币种必须一致")
        if self.submitted_only:
            account = {"assets": [], "budget_cap_cents": sum(e["payload"]["budget_cents"] for e in entries)}
        self.cleanup_previews()
        with self.store.transaction() as tx:
            state = {"plan_id": uuid4().hex, "version": 1, "submission": entries[0]["payload"],
                     "submission_revision": entries[0]["revision"], "submissions": entries,
                     "submission_sha256": entries[0]["sha256"] if len(entries) == 1 else digest(entries),
                     "sources": [source.model_dump() for source in sources], "comparisons": comparisons(sources),
                     "selected": {}, "rows": [], "approvals": {}, "audit": [], "history": [],
                     "rulings": [], "synthetic": not self.submitted_only,
                     "backend": "submitted_only" if self.submitted_only else "fixture", "generator": "deterministic_rules",
                     "warning": WARNING, "mode": "rehearsal", "customer_confirmation": "pending",
                     "execution_export_enabled": False, "enable_allowed": False,
                     "existing_assets": copy.deepcopy(account["assets"]), "budget_cap_cents": account["budget_cap_cents"]}
            for entry in entries:
                if self.submissions.read(principal, request.tenant_id, request.account_id,
                                         entry["payload"]["landing_page_id"], entry["revision"]+1):
                    raise RevisionConflict("阶段0版本过期")
            self._audit(state, principal, "created", {"submission_sha256": state["submission_sha256"]})
            tx.plans[state["plan_id"]] = state
            return self._view(state)

    def cleanup_previews(self):
        return self.store.cleanup_previews(self.clock())

    def _view(self, state):
        result = copy.deepcopy(state)
        rows = [PlanRow.model_validate(r) for r in result["rows"]]
        if rows:
            from app.sem_phase1a.contracts import Source

            result["p5"] = duplicates(rows, result["existing_assets"])
            result["p6"] = checks(rows, [Source.model_validate(s) for s in result["sources"]], result["budget_cap_cents"], result["selected"], result["rulings"])
            result["advisor_review_complete"] = all(r.row_id in result["approvals"] for r in rows)
            result["plan_sha256"] = digest({"version": result["version"], "rows": result["rows"],
                                             "selected": result["selected"], "submission_sha256": result["submission_sha256"]})
        else:
            result["p5"] = {"passed": False, "issues": [{"rule": "not_generated", "blocking": True}]}
            result["p6"] = {"passed": False, "issues": [{"rule": "unresolved_sources", "blocking": True}]}
            result["advisor_review_complete"] = False
            result["plan_sha256"] = None
        if state.get("backend") == "submitted_only":
            result["p5"]["scope"] = "batch_only_existing_assets_unverified"
            result["p5"]["passed"] = False
            result["p5"]["issues"].append({"rule": "existing_assets_unverified", "blocking": True})
            result["p6"]["passed"] = False
            result["p6"]["issues"].append({"rule": "account_cap_unverified", "blocking": True})
        result["state"] = "shadow_review" if rows else "awaiting_ruling"
        # Delivery flags are immutable constants, even if a local snapshot was modified.
        result.update(mode="rehearsal", customer_confirmation="pending",
                      execution_export_enabled=False, enable_allowed=False,
                      executable=False, go_live_allowed=False,
                      review_status_label="演练复核完成，不可执行、不可上线" if result["advisor_review_complete"]
                      else "待演练复核，不可执行、不可上线",
                      rehearsal_only_blockers=[i["rule"] for i in result["p6"]["issues"] if i.get("blocking")]
                      + ["formal_customer_confirmation_pending", "execution_disabled", "go_live_disabled"])
        return result

    def read(self, principal, plan_id):
        with self.store.transaction() as tx:
            return self._view(self._state(tx, principal, plan_id, write=False))

    def rule(self, principal, plan_id, request):
        from app.sem_phase1a.contracts import RulingRequest, Source

        request = RulingRequest.model_validate(request.model_dump())
        with self.store.transaction() as tx:
            state = self._state(tx, principal, plan_id, request.expected_version)
            selected = {c["field"]: c["default_source_id"] for c in state["comparisons"]}
            by_id = {s["source_id"]: s for s in state["sources"]}
            for field, source_id in request.choices.items():
                if field not in selected or source_id not in by_id or by_id[source_id]["field"] != field:
                    raise ShadowError("RULING_SOURCE_INVALID", "裁定只能选择该字段的已记录来源")
                selected[field] = source_id
            rows = [r.model_dump() for r in generate_bundle(
                [(LandingSubmission.model_validate(e["payload"]), e["prefix"]) for e in state["submissions"]],
                [Source.model_validate(source) for source in state["sources"]], selected)]
            if len(rows) > 1000:
                raise ShadowError("STRUCTURE_INVALID", "规划行数量超限")
            self._archive(state)
            state["selected"] = selected
            state["rows"] = rows
            state["rulings"].append({"version": state["version"], "actor": principal.actor_id,
                                     "selected": copy.deepcopy(selected), "reason": request.reason,
                                     "decisions": {field: {"source_id": source_id,
                                         "artifact_sha256": by_id[source_id]["artifact_sha256"],
                                         "actor": principal.actor_id, "reason": request.reason,
                                         "at": datetime.now(timezone.utc).isoformat()}
                                         for field, source_id in selected.items()}})
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

        self.cleanup_previews()
        with self.store.transaction() as tx:
            state = self._state(tx, principal, plan_id)
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
                       "rehearsal_only": True, "customer_confirmation": "pending", "applied": False,
                       "executable": False, "go_live_allowed": False,
                       "rehearsal_only_blockers": report["rehearsal_only_blockers"],
                       "expires_at": self.clock() + self.preview_ttl}
            tx.previews[preview_id] = {"preview": preview, "rows": parsed}
            self._audit(state, principal, "excel_preview_only", {"preview_id": preview_id, "audience": audience,
                                                                 "changes": changed, "file_sha256": hashlib.sha256(data).hexdigest()})
            return copy.deepcopy(preview)

    def apply(self, principal, plan_id, request):
        from app.sem_phase1a.contracts import ApplyRequest

        request = ApplyRequest.model_validate(request.model_dump())
        with self.store.transaction() as tx:
            state = self._state(tx, principal, plan_id, request.expected_version)
            pending = tx.previews.get(request.preview_id)
            if pending is None or pending["preview"]["plan_id"] != plan_id:
                raise ShadowError("PREVIEW_NOT_FOUND", "无该规划的预览")
            preview = pending["preview"]
            if preview["expires_at"] <= self.clock():
                raise ShadowError("PREVIEW_EXPIRED", "预览已过期")
            if preview["audience"] != "advisor":
                raise ShadowError("PREVIEW_AUDIENCE_ADVISOR_ONLY", "客户演练差异只预览，不导入正式确认链")
            if preview["applied"] or preview["base_version"] != state["version"]:
                raise RevisionConflict("预览已应用或版本已过期")
            self._archive(state)
            state["rows"] = copy.deepcopy(pending["rows"])
            preview["applied"] = True
            self._audit(state, principal, "advisor_preview_applied", {"preview_id": request.preview_id})
            return self._view(state)

    def edit_structure(self, principal, plan_id, request):
        from app.sem_phase1a.contracts import StructureRequest
        from app.sem_phase1a.structure import edit_rows

        request = StructureRequest.model_validate(request.model_dump())
        with self.store.transaction() as tx:
            state = self._state(tx, principal, plan_id, request.expected_version)
            if not state["rows"]:
                raise ShadowError("STRUCTURE_INVALID", "先完成来源裁定")
            self._archive(state)
            for step_index, operation in enumerate(request.operations, 1):
                before = copy.deepcopy(state["rows"])
                state["rows"] = edit_rows(state["rows"], operation, state["sources"])
                report = self._view(state)
                before_ids = {r["row_id"]: r for r in before}
                after_ids = {r["row_id"]: r for r in state["rows"]}
                affected = {key for key in before_ids.keys() | after_ids.keys()
                            if before_ids.get(key) != after_ids.get(key)}
                self._audit(state, principal, "structure_edited", {
                    "step_index": step_index, "operation": operation.model_dump(), "reason": request.reason,
                    "before": [r for r in before if r["row_id"] in affected],
                    "after": [r for r in state["rows"] if r["row_id"] in affected],
                    "p5": report["p5"], "p6": report["p6"]})
            return self._view(state)

    def approve(self, principal, plan_id, request):
        from app.sem_phase1a.contracts import ApprovalRequest

        request = ApprovalRequest.model_validate(request.model_dump())
        with self.store.transaction() as tx:
            state = self._state(tx, principal, plan_id, request.expected_version)
            view = self._view(state)
            if not view["p5"]["passed"]:
                raise ShadowError("DUPLICATE_BLOCKED", "精确重复硬阻断，先修改并重查")
            if any(i["rule"] in {"budget_tree", "account_cap", "negative_overlap", "text_length", "declared_boundary", "structure", "conflicts"}
                   for i in view["p6"]["issues"]):
                rule_codes = {"budget_tree": "BUDGET_INVALID", "account_cap": "BUDGET_INVALID",
                              "declared_boundary": "BUDGET_INVALID", "negative_overlap": "NEGATIVE_OVERLAP",
                              "text_length": "TEXT_LIMIT", "structure": "STRUCTURE_INVALID", "conflicts": "CONFLICT_UNRESOLVED"}
                code = next(rule_codes[i["rule"]] for i in view["p6"]["issues"] if i["rule"] in rule_codes)
                raise ShadowError(code, "存在可修订的硬检查问题，先修改并重查")
            if not state["rows"] or len(set(request.row_ids)) != len(request.row_ids):
                raise ShadowError("APPROVAL_ROWS_INVALID", "逐项批准列表为空或重复")
            ids = {r["row_id"] for r in state["rows"]}
            if not set(request.row_ids) <= ids:
                raise ShadowError("APPROVAL_ROWS_INVALID", "批准行不存在")
            for row_id in request.row_ids:
                state["approvals"][row_id] = {"actor": principal.actor_id, "reason": request.reason,
                    "version": state["version"], "plan_sha256": view["plan_sha256"], "internal_rehearsal_only": True}
            self._audit(state, principal, "rows_reviewed_internal_only", {"row_ids": request.row_ids, "reason": request.reason})
            return self._view(state)

    def export(self, principal, plan_id, audience):
        from app.sem_phase1a.excel import write_workbook

        with self.store.transaction() as tx:
            state = self._state(tx, principal, plan_id)
            view = self._view(state)
            if not view["rows"]:
                raise ShadowError("RULING_REQUIRED", "先完成来源裁定")
            if audience == "customer" and not view["advisor_review_complete"]:
                raise ShadowError("ADVISOR_REVIEW_REQUIRED", "客户演练样例须先完成顾问逐项复核")
            data = write_workbook(view, audience)
            self._audit(state, principal, "excel_exported_internal_only", {"audience": audience,
                                                                          "file_sha256": hashlib.sha256(data).hexdigest()})
            return data

    def expiry(self, principal, plan_id, now):
        with self.store.transaction() as tx:
            state = self._state(tx, principal, plan_id, write=False)
            if not state["rows"]:
                raise ShadowError("RULING_REQUIRED", "先生成影子规划")
            suggestions = []
            for entry in state["submissions"]:
                payload = LandingSubmission.model_validate(entry["payload"])
                refs = {source["source_id"] for source in state["sources"]
                        if source["field"] == entry["prefix"] + "ends_at"}
                rows = [PlanRow.model_validate(r) for r in state["rows"] if refs.intersection(r["source_refs"])]
                if rows:
                    suggestions.extend({**item, "page_id": payload.landing_page_id} for item in
                                       expiry_suggestions(payload, rows, now))
            return suggestions


def export_execution(*args, **kwargs):
    raise PermissionError("P9及以后硬关闭：无正式上传文件、无启用")


def enable_plan(*args, **kwargs):
    raise PermissionError("P9及以后硬关闭：无正式上传文件、无启用")

"""本地合成样例生成器；SQLite只放TEMP，输出仅内部样例，不启动服务。"""
from __future__ import annotations

import argparse
import io
import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import load_workbook

from app.sem_phase0.contracts import LandingSubmission
from app.sem_phase0.store import AdvisorPrincipal, SubmissionStore
from app.sem_phase1a.contracts import ApplyRequest, ApprovalRequest, CreateRequest, RulingRequest, WARNING
from app.sem_phase1a.service import ShadowService
from app.sem_phase1a.sources import FIXTURES


def build_samples(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    principal = AdvisorPrincipal("synthetic-advisor", "advisor", frozenset({(101, 201)}))
    payload = LandingSubmission.model_validate_json((FIXTURES / "submission.internal.json").read_text(encoding="utf-8"))

    def save_json(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

    def edited(data, value):
        book = load_workbook(io.BytesIO(data))
        book["内部规划"]["D8"] = value
        out = io.BytesIO()
        book.save(out)
        book.close()
        return out.getvalue()

    with TemporaryDirectory(prefix="sem-phase1a-synthetic-") as temp:
        store = SubmissionStore(Path(temp) / "synthetic.sqlite")
        store.submit(principal, payload, [])
        service = ShadowService(store)
        state = service.create(principal, CreateRequest(tenant_id=101, account_id=201,
                               page_id="synthetic-page", submission_revision=1))
        save_json("sources-and-conflicts.internal.json", state)
        state = service.rule(principal, state["plan_id"], RulingRequest(expected_version=1,
                             reason="合成顾问逐字段确认，采用识别值优先"))
        plan_id = state["plan_id"]
        original = service.export(principal, plan_id, "advisor")
        (output / "advisor.internal.xlsx").write_bytes(original)
        duplicate = service.preview(principal, plan_id, edited(original, "合成旧型号滤芯"), "advisor")
        save_json("duplicate-block.internal.json", duplicate)
        revised = edited(original, "合成滤芯选型咨询")
        (output / "advisor-edited.internal.xlsx").write_bytes(revised)
        preview = service.preview(principal, plan_id, revised, "advisor")
        save_json("advisor-preview.internal.json", preview)
        state = service.apply(principal, plan_id, ApplyRequest(expected_version=2, preview_id=preview["preview_id"]))
        for row in state["rows"]:
            state = service.approve(principal, plan_id, ApprovalRequest(expected_version=3,
                 row_ids=[row["row_id"]], reason="合成逐项演练复核，推断仍待核实，未作客户确认"))
        customer = service.export(principal, plan_id, "customer")
        (output / "customer-review.rehearsal.xlsx").write_bytes(customer)
        preview = service.preview(principal, plan_id, edited(customer, "合成客户关键词建议"), "customer")
        save_json("customer-diff.rehearsal.json", preview)
        save_json("expiry-suggestions.internal.json", service.expiry(principal, plan_id,
                  datetime.fromisoformat("2026-11-09T00:00:00+08:00")))
        save_json("planning-package.internal.json", service.read(principal, plan_id))
        assert state["advisor_review_complete"] and not state["p6"]["passed"]
        assert not state["execution_export_enabled"] and state["customer_confirmation"] == "pending"
    save_json("sample-index.internal.json", {"warning": WARNING, "synthetic": True,
              "files": sorted(p.name for p in output.iterdir() if p.is_file()),
              "generator": "python -m app.sem_phase1a.demo --output <explicit-local-directory>",
              "formal_confirmation": False, "execution_export_enabled": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=WARNING)
    parser.add_argument("--output", type=Path, required=True)
    build_samples(parser.parse_args().output)

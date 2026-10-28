"""Bounded advisor structure edits; unchanged P1 declarations remain authoritative."""
from uuid import uuid4

from app.sem_phase1a.contracts import PlanRow
from app.sem_phase1a.errors import ShadowError


def edit_rows(rows, operation, sources):
    rows = [dict(row) for row in rows]
    by_id = {row["row_id"]: row for row in rows}
    op = operation

    def fail():
        raise ShadowError("STRUCTURE_INVALID", "结构操作或父子关系不合法")

    def validate_refs(refs):
        if not refs or not set(refs) <= {source["source_id"] for source in sources}:
            fail()

    if op.action in {"add_campaign", "add_unit"}:
        parent = by_id.get(op.parent_id)
        if (op.row_id is not None or not parent or not op.text or op.budget_cents is None
                or parent["kind"] != ("project" if op.action == "add_campaign" else "campaign")):
            fail()
        refs = op.source_refs if op.source_refs is not None else parent["source_refs"]
        validate_refs(refs)
        rows.append(PlanRow(row_id="edit-" + uuid4().hex, parent_id=parent["row_id"],
                            kind="campaign" if op.action == "add_campaign" else "unit",
                            text=op.text, source_refs=refs, budget_cents=op.budget_cents,
                            verification="pending_verification").model_dump())
    else:
        row = by_id.get(op.row_id)
        if not row:
            fail()
        if op.action == "update":
            if (row["kind"] not in {"campaign", "unit"} or op.parent_id is not None
                    or op.source_refs is not None or (op.text is None and op.budget_cents is None)):
                fail()
            if op.text is not None:
                row["text"] = op.text
            if op.budget_cents is not None:
                row["budget_cents"] = op.budget_cents
            row["verification"] = "pending_verification"
        elif op.action == "delete":
            if (row["kind"] not in {"campaign", "unit"} or any(value is not None for value in
                    (op.parent_id, op.text, op.budget_cents, op.source_refs))):
                fail()
            removed = {row["row_id"]}
            while True:
                descendants = {r["row_id"] for r in rows if r["parent_id"] in removed}
                if descendants <= removed:
                    break
                removed |= descendants
            rows = [r for r in rows if r["row_id"] not in removed]
        elif op.action == "move_keyword":
            parent = by_id.get(op.parent_id)
            if (row["kind"] != "keyword" or not parent or parent["kind"] != "unit"
                    or any(value is not None for value in (op.text, op.budget_cents, op.source_refs))):
                fail()
            row["parent_id"] = parent["row_id"]
            row["verification"] = "pending_verification"
        else:
            fail()
    if len(rows) > 1000:
        fail()
    return [PlanRow.model_validate(row).model_dump() for row in rows]

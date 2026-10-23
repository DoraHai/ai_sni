"""Run the real list handler against synthetic rows; no app config or database IO."""
from __future__ import annotations

import ast
import asyncio
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Depends, HTTPException, Query
from sqlalchemy import Column, Integer, String, func, or_, select
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm.evaluator import _EvaluatorCompiler


Base = declarative_base()


class Task(Base):
    __tablename__ = "geo_content_tasks"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer)
    status = Column(String)
    pipeline_step = Column(String)
    owner_user_id = Column(Integer)
    diagnosis_audit_id = Column(Integer)
    title = Column(String)
    blocked_reason = Column(String)
    business_id = Column(Integer)
    prompt_id = Column(Integer)


def handler():
    tree = ast.parse((Path(__file__).parents[1] / "app/geo/content/routes.py").read_text(encoding="utf-8"))
    nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "WORKBENCH_TAB_STATUSES" for t in node.targets):
            nodes.append(node)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "list_tasks":
            node.decorator_list = []
            nodes.append(node)
    async def payload(session, row, detail=False):
        return {"id": row.id, "status": row.status}
    namespace = dict(Query=Query, Depends=Depends, get_session=lambda: None,
                     require_scoped_auth=lambda: None, HTTPException=HTTPException,
                     GeoContentTask=Task, select=select, func=func, or_=or_, _task_payload=payload)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "list_tasks", "exec"), namespace)
    return namespace["list_tasks"]


class SyntheticSession:
    def __init__(self):
        states = ["draft", "facts_bound", "generating", "failed", "editing", "needs_fix", "ready", "exported", "published", "published", "archived"]
        self.rows = [Task(id=i + 1, tenant_id=7, status=s, pipeline_step="draft", owner_user_id=2) for i, s in enumerate(states)]
        self.rows.append(Task(id=99, tenant_id=8, status="published"))
        self.statements = []

    def matching(self, stmt):
        self.statements.append(stmt)
        predicate = _EvaluatorCompiler(Task).process(stmt.whereclause)
        return [row for row in self.rows if predicate(row)]

    async def execute(self, stmt):
        counts = Counter(row.status for row in self.matching(stmt))
        return SimpleNamespace(all=lambda: list(counts.items()))

    async def scalar(self, stmt):
        return len(self.matching(stmt))

    async def scalars(self, stmt):
        rows = sorted(self.matching(stmt), key=lambda row: row.id, reverse=True)
        offset = stmt._offset_clause.value
        return rows[offset:offset + stmt._limit_clause.value]


def run(session, **overrides):
    params = dict(tenant_id=7, status=None, pipeline_step=None, q=None, owner_user_id=None,
                  from_diagnosis=None, include_archived=False, limit=20, offset=0,
                  ctx=SimpleNamespace(ensure_tenant=lambda tenant: None), session=session, workbench_tab=None)
    params.update(overrides)
    return asyncio.run(handler()(**params))


@pytest.mark.parametrize("tab,expected", [
    (None, [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]),
    ("draft", [4, 3, 2, 1]), ("polish", [5]), ("needs_fix", [6]),
    ("ready", [8, 7]), ("published", [10, 9]),
])
def test_counts_and_every_tab_before_pagination(tab, expected):
    session = SyntheticSession()
    first = run(session, workbench_tab=tab, limit=1)
    rest = run(session, workbench_tab=tab, offset=1)
    assert [row["id"] for row in first["items"] + rest["items"]] == expected
    assert first["total"] == rest["total"] == len(expected)
    assert first["workbench_counts"] == rest["workbench_counts"] == {
        "all": 10, "draft": 4, "polish": 1, "needs_fix": 1, "ready": 2, "published": 2,
    }
    if tab == "published":
        assert all(row["status"] == "published" for row in first["items"] + rest["items"])


def test_existing_status_and_archive_semantics():
    assert run(SyntheticSession(), status="archived")["workbench_counts"]["all"] == 1
    assert run(SyntheticSession(), include_archived=True)["total"] == 11
    assert run(SyntheticSession(), status="draft", workbench_tab="published")["total"] == 0
    assert run(SyntheticSession(), owner_user_id=3)["workbench_counts"]["all"] == 0
    assert run(SyntheticSession(), from_diagnosis=True)["total"] == 0


def test_invalid_tab_and_cross_tenant_fail_before_queries():
    session = SyntheticSession()
    with pytest.raises(HTTPException) as error:
        run(session, workbench_tab="unknown")
    assert error.value.status_code == 422
    def deny(tenant):
        raise HTTPException(403)
    with pytest.raises(HTTPException):
        run(session, ctx=SimpleNamespace(ensure_tenant=deny))
    assert session.statements == []


def test_all_three_queries_keep_advisor_and_search_scope():
    # Inspect SQL only: advisor membership is a subquery, never execute a database.
    session = SyntheticSession()
    session.matching = lambda stmt: session.statements.append(stmt) or []
    namespace = handler().__globals__
    namespace.update(GeoPrompt=Task, GeoOptimizationUnit=Task)
    Task.unit_id = Column(Integer)
    module = SimpleNamespace(assigned_scope=AsyncMock(return_value=(None, [31])))
    with patch.dict("sys.modules", {"app.security.advisor_write_reads": module}):
        params = dict(tenant_id=7, status=None, pipeline_step="draft", q="example", owner_user_id=2,
                      from_diagnosis=False, include_archived=False, limit=20, offset=0,
                      ctx=SimpleNamespace(ensure_tenant=lambda tenant: None, advisor_scope=True),
                      session=session, workbench_tab="published")
        asyncio.run(namespace["list_tasks"](**params))
    assert len(session.statements) == 3
    for stmt in session.statements:
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "tenant_id = 7" in sql and "business_id IN (31)" in sql
        assert "prompt_id IN (SELECT" in sql and "%example%" in sql
        assert "owner_user_id = 2" in sql and "diagnosis_audit_id IS NULL" in sql
    assert "status IN ('published')" not in str(session.statements[0])

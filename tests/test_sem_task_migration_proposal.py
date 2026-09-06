"""Review the inactive proposal without importing or invoking Alembic."""
import ast
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, dialect
from sqlalchemy.schema import CreateIndex, CreateTable

ROOT = Path(__file__).parents[1]
PROPOSAL = ROOT / "docs/migration_proposals/0095_sem_tasks.py"


class Recorder:
    """In-memory SQLAlchemy definitions only; never a database executor."""
    def __init__(self):
        self.metadata = sa.MetaData()
        sa.Table("tenants", self.metadata, sa.Column("id", sa.BigInteger(), primary_key=True))
        self.calls = []

    def create_table(self, name, *args):
        self.calls.append(("table", name))
        sa.Table(name, self.metadata, *args)

    def create_index(self, name, table, columns):
        self.calls.append(("index", name))
        sa.Index(name, *(self.metadata.tables[table].c[c] for c in columns))


def proposal_definitions():
    tree = ast.parse(PROPOSAL.read_text(encoding="utf-8"))
    # Only literal metadata assignments and function definitions are evaluated.
    # All imports (including Alembic) are excluded. op is an in-memory recorder.
    body = [n for n in tree.body if isinstance(n, (ast.Assign, ast.FunctionDef))]
    recorder = Recorder()
    namespace = {"sa": sa, "JSONB": JSONB, "op": recorder}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(PROPOSAL), "exec"), namespace)
    namespace["upgrade"]()
    return namespace, recorder


def test_candidate_contract_is_inactive_and_explicit():
    namespace, recorder = proposal_definitions()
    assert namespace["revision"] == "0095_sem_tasks"
    assert namespace["down_revision"] == "0094_seo_qa_batches"
    assert not list((ROOT / "migrations/versions").glob("*0095*"))
    assert recorder.calls == [("table", "sem_tasks"), ("index", "ix_sem_tasks_action"),
                              ("index", "ix_sem_tasks_queue")]
    assert "script_location = migrations" in (ROOT / "alembic.ini").read_text()


def test_proposal_ddl_matches_reviewed_sql():
    _, recorder = proposal_definitions()
    table = recorder.metadata.tables["sem_tasks"]
    actual = [str(CreateTable(table).compile(dialect=dialect()))]
    actual += [str(CreateIndex(i).compile(dialect=dialect())) for i in table.indexes]
    source = (ROOT / "docs/SEM_TASK_SCHEMA_REVIEW.sql").read_text(encoding="utf-8")
    source = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("--"))
    assert list(table.primary_key.columns.keys()) == ["id"]
    foreign_key, = table.foreign_keys
    assert foreign_key.parent.name == "tenant_id"
    assert foreign_key.target_fullname == "tenants.id" and foreign_key.ondelete == "RESTRICT"
    def normalize(s):
        # Equivalent inline/table-level PK and FK are asserted above.
        s = "".join(s.split()).rstrip(";")
        return (s.replace("idBIGSERIALNOTNULLPRIMARYKEY", "idBIGSERIALNOTNULL")
                .replace(",PRIMARYKEY(id)", "")
                .replace(",FOREIGNKEY(tenant_id)REFERENCEStenants(id)ONDELETERESTRICT", "")
                .replace("REFERENCEStenants(id)ONDELETERESTRICT", ""))
    expected = [normalize(s) for s in source.split(";") if s.strip()]
    actual = [normalize(" ".join(s.split()).rstrip(";")) for s in actual]
    assert sorted(actual) == sorted(expected)


def test_downgrade_refuses_to_delete_audit_data():
    namespace, recorder = proposal_definitions()
    previous = list(recorder.calls)
    with pytest.raises(RuntimeError, match="Destructive rollback"):
        namespace["downgrade"]()
    assert recorder.calls == previous


def test_proposal_upgrade_contains_only_additive_sem_operations():
    tree = ast.parse(PROPOSAL.read_text(encoding="utf-8"))
    upgrade = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    assert len(upgrade.body) == 3
    for node in upgrade.body:
        assert isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        call = node.value
        assert isinstance(call.func, ast.Attribute) and call.func.value.id == "op"
        assert call.func.attr in {"create_table", "create_index"}
    assert "from app" not in PROPOSAL.read_text(encoding="utf-8")

"""Pinned source bundle and strictly LOCAL rehearsal. No production entry point."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOCK = json.loads((HERE / "SOURCE_LOCK.json").read_text(encoding="utf-8"))
START = LOCK["start_revision"]
TARGET = LOCK["target_revision"]
TARGET_FILE = "migrations/versions/20260906_0095_sem_tasks.py"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def local_sources():
    return {
        TARGET_FILE: (ROOT / "docs/migration_proposals/0095_sem_tasks.py").read_bytes(),
        "migrations/env.py": (HERE / "env.py").read_bytes(),
    }


def build(destination):
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Bundle destination must not exist")
    # Validate every source before creating output. Read Git blobs, not checkout
    # files, so original historical bytes survive platform line endings.
    payload = {}
    for name, expected in LOCK["files"].items():
        data = subprocess.check_output(
            ["git", "show", LOCK["source_commit"] + ":" + name], cwd=ROOT)
        if digest(data) != expected:
            raise ValueError("Pinned source mismatch: " + name)
        payload[name] = data
    payload.update(local_sources())
    destination.mkdir(parents=False)
    for name, data in payload.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {"source_commit": LOCK["source_commit"], "start_revision": START,
                "target_revision": TARGET, "purpose": "local-rehearsal-only",
                "files": {name: digest(data) for name, data in sorted(payload.items())}}
    (destination / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return verify(destination)


def verify(bundle):
    bundle = Path(bundle)
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("Bundle must be a real directory")
    members = list(bundle.rglob("*"))
    if any(p.is_symlink() for p in members):
        raise ValueError("Bundle links are forbidden")
    manifest = json.loads((bundle / "MANIFEST.json").read_text(encoding="utf-8"))
    expected = dict(LOCK["files"])
    expected.update({p: digest(data) for p, data in local_sources().items()})
    if (manifest.get("files") != expected or manifest.get("source_commit") != LOCK["source_commit"]
            or manifest.get("start_revision") != START or manifest.get("target_revision") != TARGET
            or manifest.get("purpose") != "local-rehearsal-only"):
        raise ValueError("Bundle contract does not match reviewed sources")
    if {p.relative_to(bundle).as_posix() for p in members if p.is_file()} != set(expected) | {"MANIFEST.json"}:
        raise ValueError("Unexpected or missing bundle files")
    for name, sha in expected.items():
        if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
            raise ValueError("Unsafe member")
        if digest((bundle / name).read_bytes()) != sha:
            raise ValueError("Bundle content mismatch: " + name)
    return manifest


def configuration(bundle):
    verify(bundle)  # Before Alembic can import any migration module.
    # Run in a fresh isolated interpreter: historical helpers must come from
    # this bundle, not an application's previously imported modules.
    if any(n == "app" or n.startswith("app.") for n in sys.modules):
        raise ValueError("Use a fresh interpreter, not an application process")
    sys.path.insert(0, str(Path(bundle).resolve()))
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option("script_location", str((Path(bundle) / "migrations").resolve()).replace("%", "%%"))
    script = ScriptDirectory.from_config(cfg)
    if script.get_heads() != [TARGET]:
        raise ValueError("Expected exactly the pinned target head")
    revisions = list(script.iterate_revisions(TARGET, START))
    if [r.revision for r in revisions] != [TARGET] or revisions[0].down_revision != START:
        raise ValueError("Plan must contain only the SemTask revision")
    return cfg


def validate_local_url(url, schema):
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    if (parsed.drivername != "postgresql+asyncpg" or parsed.host != "127.0.0.1"
            or parsed.database != "sem_tasks_migration_test" or parsed.query
            or not parsed.port or not re.fullmatch(r"sem_migration_test_[0-9a-f]{32}", schema)):
        raise ValueError("Only explicit loopback dedicated test database/schema is permitted")
    return parsed


async def rehearse(bundle, url, schema, *, inject_after_create=False):
    # inject_after_create is an in-process test hook, never a CLI operation.
    parsed = validate_local_url(url, schema)
    cfg = configuration(bundle)
    from sqlalchemy import text, event
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    from alembic import command
    engine = create_async_engine(parsed, poolclass=NullPool, hide_parameters=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('search_path', :s, true)"), {"s": schema})
            await conn.execute(text("SET LOCAL lock_timeout = '1s'"))
            await conn.execute(text("SET LOCAL statement_timeout = '10s'"))
            await conn.execute(text("LOCK TABLE alembic_version IN EXCLUSIVE MODE"))
            revisions = list((await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars())
            if revisions != [START]:
                raise ValueError("Starting revision must be exactly the approved single row")
            for name in ("sem_tasks", "sem_tasks_id_seq", "ix_sem_tasks_action", "ix_sem_tasks_queue"):
                if await conn.scalar(text("SELECT to_regclass(:name)"), {"name": schema + "." + name}):
                    raise ValueError("Target object already exists: " + name)
            if inject_after_create:
                def fail_on_index(connection, cursor, statement, parameters, context, executemany):
                    if statement.startswith("CREATE INDEX ix_sem_tasks_"):
                        raise RuntimeError("Injected failure after table creation")
                event.listen(engine.sync_engine, "before_cursor_execute", fail_on_index)
            def execute(sync):
                cfg.attributes.update(connection=sync, test_schema=schema, local_test_authorized=True)
                command.upgrade(cfg, TARGET)
            await conn.run_sync(execute)
            final = list((await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars())
            if final != [TARGET]:
                raise ValueError("Unexpected final revision")
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["build", "verify", "plan", "local-upgrade"])
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--schema")
    args = parser.parse_args()
    if args.mode == "build":
        manifest = build(args.bundle)
        print("bundle files=" + str(len(manifest["files"])))
    elif args.mode == "verify":
        verify(args.bundle)
        print("bundle=verified")
    elif args.mode == "plan":
        configuration(args.bundle)
        print(START + " -> " + TARGET + " (one revision; no database connection)")
    else:
        import asyncio
        asyncio.run(rehearse(args.bundle, os.environ.get("SEM_TASK_MIGRATION_TEST_DATABASE_URL", ""), args.schema or ""))
        print("local migration rehearsal=passed")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Driver errors can contain DSNs; do not render them in this CLI.
        print("Local rehearsal refused/failed: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)

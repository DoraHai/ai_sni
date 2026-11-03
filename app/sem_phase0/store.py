"""独立私有SQLite契约存储。只接受显式本地路径，不读取应用配置或生产库。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.sem_phase0.contracts import LandingSubmission
from app.sem_phase0.screenshots import MAX_IMAGES, MAX_TOTAL_BYTES, Screenshot, clean_screenshot


class ScopeDenied(Exception):
    pass


class RevisionConflict(Exception):
    pass


@dataclass(frozen=True)
class AdvisorPrincipal:
    """必须由可信服务端鉴权适配器构造；不能从表单、Header裸值或客户端JSON构造。"""
    actor_id: str
    role: str
    # 已验证账户归属于tenant，顾问对该账户有SEM提交权限，且账户SEM未暂停。
    writable_accounts: frozenset[tuple[int, int]]
    readable_accounts: frozenset[tuple[int, int]] = frozenset()


def check_scope(principal: AdvisorPrincipal, tenant_id: int, account_id: int, *, write=True):
    allowed = (principal.writable_accounts if write else
               principal.readable_accounts | (principal.writable_accounts if principal.role == "advisor" else frozenset()))
    if ((write and principal.role != "advisor") or principal.role not in {"advisor", "customer"}
            or not principal.actor_id.strip() or (tenant_id, account_id) not in allowed):
        raise ScopeDenied("无该租户账户的顾问提交权限" if write else "无该租户账户的读取权限")


class SubmissionStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS phase0_pages (
                    tenant INTEGER NOT NULL, account INTEGER NOT NULL, page TEXT NOT NULL,
                    product TEXT NOT NULL, url TEXT NOT NULL,
                    PRIMARY KEY (tenant, account, page));
                CREATE TABLE IF NOT EXISTS phase0_submissions (
                    tenant INTEGER NOT NULL, account INTEGER NOT NULL, page TEXT NOT NULL,
                    revision INTEGER NOT NULL, actor TEXT NOT NULL, submitted_at TEXT NOT NULL,
                    payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                    PRIMARY KEY (tenant, account, page, revision));
                CREATE TABLE IF NOT EXISTS phase0_screenshots (
                    tenant INTEGER NOT NULL, account INTEGER NOT NULL, page TEXT NOT NULL,
                    revision INTEGER NOT NULL, ordinal INTEGER NOT NULL,
                    metadata TEXT NOT NULL, clean_bytes BLOB NOT NULL,
                    PRIMARY KEY (tenant, account, page, revision, ordinal));
            """)

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def submit(self, principal: AdvisorPrincipal, payload: LandingSubmission,
               screenshots: list[Screenshot]) -> dict:
        # Revalidate even if a non-HTTP caller used model_construct/model_copy.
        payload = LandingSubmission.model_validate(payload.model_dump())
        scope = payload.tenant_id, payload.account_id, payload.landing_page_id
        check_scope(principal, *scope[:2])
        if len(screenshots) > MAX_IMAGES or sum(len(s.data) for s in screenshots) > MAX_TOTAL_BYTES:
            raise ValueError("每页截图数量或合计大小超限")
        if any(s.landing_page_id != payload.landing_page_id for s in screenshots):
            raise ValueError("截图不得跨页混配")
        cleaned = [clean_screenshot(s) for s in screenshots]
        if sum(len(data) for data, _ in cleaned) > MAX_TOTAL_BYTES:
            raise ValueError("每页清洗截图合计超限")
        content = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False,
                             sort_keys=True, separators=(",", ":"))
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        submitted_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            page = db.execute("SELECT product,url FROM phase0_pages WHERE tenant=? AND account=? AND page=?",
                              scope).fetchone()
            if page and page != (payload.product_line_id, payload.landing_url):
                raise RevisionConflict("页面ID已绑定产品线及URL；新页面须使用独立ID")
            latest = db.execute("SELECT COALESCE(MAX(revision),0) FROM phase0_submissions "
                                "WHERE tenant=? AND account=? AND page=?", scope).fetchone()[0]
            if latest != payload.expected_revision:
                raise RevisionConflict("提交版本冲突，请重新读取后提交")
            revision = latest + 1
            db.execute("INSERT OR IGNORE INTO phase0_pages VALUES (?,?,?,?,?)",
                       (*scope, payload.product_line_id, payload.landing_url))
            db.execute("INSERT INTO phase0_submissions VALUES (?,?,?,?,?,?,?,?)",
                       (*scope, revision, principal.actor_id, submitted_at, content, content_hash))
            for ordinal, (data, meta) in enumerate(cleaned, 1):
                db.execute("INSERT INTO phase0_screenshots VALUES (?,?,?,?,?,?,?)",
                           (*scope, revision, ordinal, json.dumps(meta), data))
        return {"landing_page_id": payload.landing_page_id, "revision": revision,
                "submitted_by": principal.actor_id, "submitted_at": submitted_at,
                "payload_sha256": content_hash, "screenshot_count": len(cleaned),
                "state": "blocked_draft", "customer_confirmation": "pending",
                "execution_export_enabled": False}

    def read(self, principal: AdvisorPrincipal, tenant: int, account: int, page: str,
             revision: int) -> dict | None:
        check_scope(principal, tenant, account, write=False)
        with closing(self._connect()) as db:
            row = db.execute("SELECT actor,submitted_at,payload,payload_sha256 FROM phase0_submissions "
                             "WHERE tenant=? AND account=? AND page=? AND revision=?",
                             (tenant, account, page, revision)).fetchone()
            if row is None:
                return None
            shots = db.execute("SELECT ordinal,metadata FROM phase0_screenshots "
                               "WHERE tenant=? AND account=? AND page=? AND revision=? ORDER BY ordinal",
                               (tenant, account, page, revision)).fetchall()
        # Stored data is untrusted too: validate contract, digest and scope bindings on every read.
        try:
            payload = LandingSubmission.model_validate_json(row[2])
            valid_hash = hashlib.sha256(row[2].encode("utf-8")).hexdigest() == row[3]
            valid_scope = (payload.tenant_id, payload.account_id, payload.landing_page_id,
                           payload.expected_revision + 1) == (tenant, account, page, revision)
            if not valid_hash or not valid_scope:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("阶段0存储校验失败") from None
        return {"submitted_by": row[0], "submitted_at": row[1], "payload": payload.model_dump(mode="json"),
                "payload_sha256": row[3], "revision": revision, "state": "blocked_draft",
                "customer_confirmation": "pending", "execution_export_enabled": False,
                "screenshots": [{"ordinal": n, **json.loads(meta)} for n, meta in shots]}

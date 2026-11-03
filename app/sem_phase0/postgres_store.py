"""Injected transactional source repository; never creates engines or local files.

Binary backend must implement immutable private put/read with bounded operations.
No backend is configured by this slice. No OCR, decoder, URL fetch or execution.
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import text

from app.sem_phase0.contracts import LandingSubmission
from app.sem_phase0.screenshots import MAX_IMAGES, MAX_IMAGE_BYTES, MAX_TOTAL_BYTES
from app.sem_phase0.store import (AttachmentUnavailable, RevisionConflict, check_scope)


class PrivateAttachmentStore(Protocol):
    def put_if_absent(self, key: str, data: bytes, sha256: str) -> None: ...
    def read(self, key: str, max_bytes: int) -> bytes: ...


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(value).hexdigest()


def attachment(item, page):
    data = item.data
    if item.landing_page_id != page or not 0 < len(data) <= MAX_IMAGE_BYTES:
        raise ValueError('附件不满足大小或页面契约')
    # Signature-only whitelist; bytes remain inert. No image decoding/parsing.
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
    elif data.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    elif len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        mime = 'image/webp'
    else:
        raise ValueError('附件类型不满足契约')
    return {'sha256': sha(data), 'size': len(data), 'mime': mime,
            'ocr_status': 'not_connected', 'validation': 'signature_only_untrusted'}


class SQLAlchemySubmissionStore:
    def __init__(self, connection_factory, attachments: PrivateAttachmentStore | None = None):
        self.connection_factory = connection_factory
        self.attachments = attachments

    def submit(self, principal, payload, screenshots):
        payload = LandingSubmission.model_validate(payload.model_dump())
        check_scope(principal, payload.tenant_id, payload.account_id)
        if screenshots and self.attachments is None:
            raise AttachmentUnavailable()
        if len(screenshots) > MAX_IMAGES or sum(len(s.data) for s in screenshots) > MAX_TOTAL_BYTES:
            raise ValueError('附件数量或合计大小超限')
        metadata = [attachment(s, payload.landing_page_id) for s in screenshots]
        content = canonical(payload.model_dump(mode='json'))
        params = {'tid': payload.tenant_id, 'aid': payload.account_id, 'page': payload.landing_page_id}
        with self.connection_factory() as db:
            if db.dialect.name == 'sqlite':
                # Only disposable fixtures use SQLite, with an independent UOW.
                if not db.info.get('sem_source_bound'):
                    db.exec_driver_sql('BEGIN IMMEDIATE')
            lock = ' FOR UPDATE' if db.dialect.name == 'postgresql' else ''
            # Account lock serializes even the first submission of a new page.
            account = db.execute(text("SELECT id FROM baidu_accounts WHERE id=:aid AND tenant_id=:tid "
                                      "AND status='active'" + lock), params).first()
            if account is None:
                from app.sem_phase0.store import ScopeDenied
                raise ScopeDenied('账户不可用')
            page = db.execute(text('SELECT product_id,url FROM sem_phase0_pages WHERE '
                'tenant_id=:tid AND account_id=:aid AND page_id=:page' + lock), params).first()
            if page and tuple(page) != (payload.product_line_id, payload.landing_url):
                raise RevisionConflict('页面身份绑定已变化')
            latest = db.execute(text('SELECT COALESCE(MAX(revision),0) FROM sem_phase0_submissions '
                'WHERE tenant_id=:tid AND account_id=:aid AND page_id=:page'), params).scalar_one()
            if latest != payload.expected_revision:
                raise RevisionConflict('提交版本冲突')
            revision = latest + 1
            manifest = []
            for ordinal, (shot, meta) in enumerate(zip(screenshots, metadata), 1):
                key = (f'sem-sources/{payload.tenant_id}/{payload.account_id}/{payload.landing_page_id}/'
                       f'{revision}/{ordinal}-{meta["sha256"]}')
                try:
                    self.attachments.put_if_absent(key, shot.data, meta['sha256'])
                    stored = self.attachments.read(key, MAX_IMAGE_BYTES + 1)
                    if len(stored) != meta['size'] or sha(stored) != meta['sha256']:
                        raise ValueError
                except Exception:
                    raise AttachmentUnavailable() from None
                manifest.append({'ordinal': ordinal, 'object_key': key, 'metadata': meta})
            if not page:
                db.execute(text('INSERT INTO sem_phase0_pages(tenant_id,account_id,page_id,product_id,url) '
                    'VALUES(:tid,:aid,:page,:product,:url)'),
                    {**params, 'product': payload.product_line_id, 'url': payload.landing_url})
            at = datetime.now(timezone.utc).isoformat()
            db.execute(text('INSERT INTO sem_phase0_submissions(tenant_id,account_id,page_id,revision,'
                'actor_id,submitted_at,payload,payload_sha256,attachments_sha256) '
                'VALUES(:tid,:aid,:page,:rev,:actor,:at,:payload,:sha,:attachments)'),
                {**params, 'rev': revision, 'actor': int(principal.actor_id), 'at': at, 'payload': content,
                 'sha': sha(content.encode('utf-8')), 'attachments': sha(canonical(manifest).encode('utf-8'))})
            for entry in manifest:
                db.execute(text('INSERT INTO sem_phase0_attachments(tenant_id,account_id,page_id,revision,'
                    'ordinal,object_key,metadata) VALUES(:tid,:aid,:page,:rev,:ordinal,:key,:meta)'),
                    {**params, 'rev': revision, 'ordinal': entry['ordinal'], 'key': entry['object_key'],
                     'meta': canonical(entry['metadata'])})
        return {'landing_page_id': payload.landing_page_id, 'revision': revision,
                'submitted_by': principal.actor_id, 'submitted_at': at,
                'payload_sha256': sha(content.encode('utf-8')), 'screenshot_count': len(manifest),
                'state': 'blocked_draft', 'customer_confirmation': 'pending', 'execution_export_enabled': False}

    def read(self, principal, tenant, account, page, revision):
        check_scope(principal, tenant, account, write=False)
        params = {'tid': tenant, 'aid': account, 'page': page, 'rev': revision}
        with self.connection_factory() as db:
            lock = ' FOR SHARE' if db.dialect.name == 'postgresql' else ''
            identity = db.execute(text('SELECT product_id,url FROM sem_phase0_pages WHERE '
                'tenant_id=:tid AND account_id=:aid AND page_id=:page' + lock), params).first()
            row = db.execute(text('SELECT actor_id,submitted_at,payload,payload_sha256,attachments_sha256 '
                'FROM sem_phase0_submissions WHERE tenant_id=:tid AND account_id=:aid AND page_id=:page '
                'AND revision=:rev'), params).first()
            if row is None:
                return None
            shots = db.execute(text('SELECT ordinal,object_key,metadata FROM sem_phase0_attachments '
                'WHERE tenant_id=:tid AND account_id=:aid AND page_id=:page AND revision=:rev ORDER BY ordinal'), params).all()
        try:
            payload = LandingSubmission.model_validate_json(row[2])
            if (sha(row[2].encode('utf-8')) != row[3]
                    or (payload.tenant_id, payload.account_id, payload.landing_page_id, payload.expected_revision+1)
                    != (tenant, account, page, revision)
                    or identity is None or tuple(identity) != (payload.product_line_id, payload.landing_url)):
                raise ValueError
            manifest = [{'ordinal': n, 'object_key': key, 'metadata': json.loads(meta)} for n, key, meta in shots]
            if (len(manifest) > MAX_IMAGES or [e['ordinal'] for e in manifest] != list(range(1, len(manifest)+1))
                    or sha(canonical(manifest).encode('utf-8')) != row[4]):
                raise ValueError
            total = 0
            for entry in manifest:
                meta, key = entry['metadata'], entry['object_key']
                if key != f'sem-sources/{tenant}/{account}/{page}/{revision}/{entry["ordinal"]}-{meta["sha256"]}':
                    raise ValueError
                if self.attachments is None:
                    raise AttachmentUnavailable()
                try:
                    data = self.attachments.read(key, MAX_IMAGE_BYTES + 1)
                except Exception:
                    raise AttachmentUnavailable() from None
                from app.sem_phase0.screenshots import Screenshot
                if attachment(Screenshot(page, '', '', data), page) != meta:
                    raise ValueError
                total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise ValueError('阶段0存储校验失败') from None
        # Private object keys and raw binary never leave the repository.
        return {'submitted_by': str(row[0]), 'submitted_at': row[1], 'payload': payload.model_dump(mode='json'),
                'payload_sha256': row[3], 'revision': revision, 'state': 'blocked_draft',
                'customer_confirmation': 'pending', 'execution_export_enabled': False,
                'screenshots': [{'ordinal': e['ordinal'], **e['metadata']} for e in manifest]}

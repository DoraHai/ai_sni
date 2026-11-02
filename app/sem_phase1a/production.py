"""Production composition using only the caller's existing async DB engine."""
from contextlib import contextmanager
import logging
import os

from app.sem_phase0.postgres_store import SQLAlchemySubmissionStore
from app.sem_phase1a.postgres_store import SQLAlchemyShadowStore
from app.sem_phase1a.service import ShadowService
from app.sem_phase1a.grant_management import AccountGrantService, GrantError


ATTACHMENT_OSS_VARIABLES = (
    'SEM_ATTACHMENT_OSS_BUCKET',
    'SEM_ATTACHMENT_OSS_ENDPOINT',
    'SEM_ATTACHMENT_OSS_REGION',
    'SEM_ATTACHMENT_OSS_ACCESS_KEY_ID',
    'SEM_ATTACHMENT_OSS_ACCESS_KEY_SECRET',
)


def attachment_store_from_environment():
    """Construct a client locally; incomplete/invalid config leaves attachments off.

    Never probe/create a bucket, log configuration or report SDK exceptions.
    The SDK can log endpoints and signed headers at DEBUG, so its diagnostics
    and the HTTP connection diagnostics are disabled before constructing it.
    """
    try:
        values = [os.environ.get(name, '').strip() for name in ATTACHMENT_OSS_VARIABLES]
        if not all(values):
            return None
        bucket_name, endpoint, region, access_key_id, access_key_secret = values
        import oss2
        from app.sem_phase0.oss_attachments import (
            OSSPrivateAttachmentStore, CONNECT_TIMEOUT_SECONDS, IO_TIMEOUT_SECONDS,
        )
        for name in list(logging.Logger.manager.loggerDict):
            if name == 'oss2' or name.startswith('oss2.') or name == 'urllib3.connectionpool':
                logging.getLogger(name).disabled = True
        auth = oss2.AuthV4(access_key_id, access_key_secret)
        bucket = oss2.Bucket(auth, endpoint, bucket_name, region=region,
                             connect_timeout=(CONNECT_TIMEOUT_SECONDS, IO_TIMEOUT_SECONDS))
        return OSSPrivateAttachmentStore(bucket)
    except Exception:
        # Config, import and SDK failures must not abort application startup.
        return None


class ProductionAccountGrantService(AccountGrantService):
    """An uninitialized account cannot bootstrap itself through the public API."""
    async def _account(self, db, tenant_id, account_id, *, active):
        await super()._account(db, tenant_id, account_id, active=active)
        existing = await self._row(db, 'SELECT user_id FROM sem_phase1a_account_grants '
            'WHERE account_id=:aid AND tenant_id=:tid AND revoked_at IS NULL LIMIT 1',
            {'aid': account_id, 'tid': tenant_id}, lock=False)
        if existing is None:
            raise GrantError('GRANT_ACCOUNT_NOT_INITIALIZED', 403)


class ProductionServices:
    def __init__(self, engine, attachments=None):
        self.engine, self.attachments = engine, attachments

    async def call(self, kind, method, *args):
        async with self.engine.begin() as connection:
            def operation(db):
                if db.dialect.name == 'sqlite':
                    db.exec_driver_sql('BEGIN IMMEDIATE')
                db.info['sem_source_bound'] = True
                @contextmanager
                def bound():
                    yield db
                try:
                    sources = SQLAlchemySubmissionStore(bound, self.attachments)
                    service = (sources if kind == 'sources' else
                               ShadowService(sources, SQLAlchemyShadowStore(bound), submitted_only=True))
                    return getattr(service, method)(*args)
                finally:
                    db.info.pop('sem_source_bound', None)
            return await connection.run_sync(operation)

    def proxy(self, kind):
        owner = self
        class Proxy:
            def __getattr__(self, method):
                async def call(*args):
                    return await owner.call(kind, method, *args)
                return call
        return Proxy()


def routers(engine, session_factory):
    from app.sem_phase0.router import create_router as sources_router
    from app.sem_phase1a.router import create_router as shadow_router
    from app.sem_phase1a.grant_router import create_grant_router
    from app.sem_phase1a.production_principals import production_principal_dependency
    services = ProductionServices(engine, attachments=attachment_store_from_environment())
    principal = production_principal_dependency()
    return (sources_router(services.proxy('sources'), principal),
            shadow_router(services.proxy('shadow'), principal),
            create_grant_router(ProductionAccountGrantService(session_factory.begin)))

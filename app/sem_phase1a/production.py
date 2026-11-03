"""Production composition using only the caller's existing async DB engine."""
from contextlib import contextmanager

from app.sem_phase0.postgres_store import SQLAlchemySubmissionStore
from app.sem_phase1a.postgres_store import SQLAlchemyShadowStore
from app.sem_phase1a.service import ShadowService
from app.sem_phase1a.grant_management import AccountGrantService, GrantError


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
    services = ProductionServices(engine)
    principal = production_principal_dependency()
    return (sources_router(services.proxy('sources'), principal),
            shadow_router(services.proxy('shadow'), principal),
            create_grant_router(ProductionAccountGrantService(session_factory.begin)))

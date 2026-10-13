"""Independent production distribution unit using native named-user auth.

No scheduler, token issuance, platform login or automatic publication. Package
assembly uses the tracked minimal API initializer instead of the SEM registry.
"""
from contextlib import asynccontextmanager
from pathlib import Path
import json

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.database import async_session_factory, engine
from app.security.prod_guard import enforce_production_secrets
from app.api.distribution import legacy_router, capability_router, handoff_router
from app.api.distribution_pairing import router as pairing_router
from app.api.distribution_task_resolution_read import router as resolution_router
from app.api.seo_distribution_media import router as media_router
from app.api.distribution_nord_onboarding import router as nord_onboarding_router

ROOT = Path(__file__).resolve().parents[1]


async def readiness():
    """Read-only catalog checks, with no client/project data in the response."""
    policy = json.loads((ROOT / 'scripts/nord_distribution_acl_policy.json').read_text())
    async with async_session_factory() as session:
        await session.execute(text('SET TRANSACTION READ ONLY'))
        identity = (await session.execute(text("SELECT current_database() db, current_user role," 
            "(SELECT count(*) FROM public.alembic_version) versions,"
            "(SELECT min(version_num) FROM public.alembic_version) baseline"))).mappings().one()
        if dict(identity) != {'db': 'sem_prod', 'role': 'sem_runtime',
                              'versions': 1, 'baseline': '0107_seo_site_delete'}:
            raise RuntimeError('Distribution database identity/baseline differs')
        for name in policy['tables']:
            if not await session.scalar(text('SELECT to_regclass(:name) IS NOT NULL'), {'name': 'public.'+name}):
                raise RuntimeError('Core distribution schema unavailable')
        for name, expected in policy['table_privileges'].items():
            for privilege in ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'):
                actual = await session.scalar(text('SELECT has_table_privilege(current_user,:name,:p)'),
                    {'name':'public.'+name,'p':privilege})
                if actual != (privilege in expected):
                    raise RuntimeError('Core distribution table ACL differs')
        for name in policy['sequence_privileges']:
            for privilege in ('USAGE','SELECT','UPDATE'):
                actual = await session.scalar(text('SELECT has_sequence_privilege(current_user,:name,:p)'),
                    {'name':'public.'+name,'p':privilege})
                if actual != (privilege == 'USAGE'):
                    raise RuntimeError('Core distribution sequence ACL differs')
        seo_storage = await session.scalar(text("SELECT count(*) FROM unnest(ARRAY["
            "'seo_distribution_media_sets','seo_distribution_media_bytes',"
            "'seo_distribution_media_reviews','seo_distribution_result_events',"
            "'nord_seo_site_purge_context']) n "
            "WHERE to_regclass('public.'||n) IS NOT NULL"))
        if seo_storage not in (0,5):
            raise RuntimeError('Incomplete SEO publication storage')
        if seo_storage==5:
            seo_policy=json.loads((ROOT/'scripts/nord_seo_distribution_storage_policy.json').read_text())
            for name in seo_policy['tables']+seo_policy['private_tables']:
                for privilege in ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'):
                    actual=await session.scalar(text('SELECT has_table_privilege(current_user,:name,:p)'),
                        {'name':'public.'+name,'p':privilege})
                    expected=name in seo_policy['tables'] and privilege in ('SELECT','INSERT')
                    if actual != expected:raise RuntimeError('SEO publication storage ACL differs')
            for name,definer in [('nord_seo_distribution_immutable',False),('nord_seo_site_purge_context_guard',True)]:
                verified=await session.scalar(text("SELECT count(*)=1 FROM pg_proc WHERE oid=to_regprocedure(:name) "
                    "AND prosecdef=:definer AND pg_get_userbyid(proowner)='sem_app' "
                    "AND proconfig=ARRAY['search_path=pg_catalog'] "
                    "AND NOT has_function_privilege(current_user,oid,'EXECUTE')"),
                    {'name':'public.'+name+'()','definer':definer})
                if not verified:raise RuntimeError('SEO publication guard configuration differs')
    return {'db': 'ok', 'core_tables': len(policy['tables']),
            'seo_publication_storage_ready': seo_storage == 5,
            'automatic_publish': False, 'remote_control': False}


@asynccontextmanager
async def lifespan(app):
    settings = get_settings()
    if settings.app_env.lower() not in {'prod','production'}:
        raise RuntimeError('This entry requires production configuration')
    enforce_production_secrets(settings, hard_fail=True)
    await readiness()
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title='GSnipers Distribution', version='1.0.0', lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
for router in (legacy_router, capability_router, handoff_router, pairing_router,resolution_router,media_router,nord_onboarding_router):
    app.include_router(router)


@app.get('/health/distribution')
async def health():
    try:
        status = await readiness()
        manifest = json.loads((ROOT / 'release-manifest.json').read_text())
        return JSONResponse({'status':'ok', 'release_commit':manifest['release_commit'], **status},
                            headers={'Cache-Control':'no-store'})
    except Exception:
        return JSONResponse({'status':'unavailable'}, status_code=503,
                            headers={'Cache-Control':'no-store'})

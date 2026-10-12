"""One module per process, native auth/models/adapters, owned acceptance DB only."""
import argparse
import asyncio
import base64
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import types

from distribution_server_pilot_environment import PORTS, read, write, owned
from distribution_assembled_worker import assemble, HEADS

REVIEWED_ACCEPTANCE_HEADS={'seo':{'b4d8387123355348f79e26ea2838585c5106a4b9',
    '3087e62f23e799fe82d279f79f698f0499bf3a27'},
    'geo':{'46dacbd805afc00f37eba344306fde004039efed'}}
CUSTOMER_READS = (
    ('get_workbench_service_status', '/api/v1/seo/workbench/service-status'),
    ('list_executions', '/api/v1/seo/workbench/executions'),
    ('list_tasks', '/api/v1/seo/workbench/onsite-tasks'),
    ('list_site_pages', '/api/v1/seo/site-pages'),
    ('list_workbench_publication_page_evidence', '/api/v1/seo/workbench/publication-page-evidence'),
)
EVIDENCE_READ_PATH = CUSTOMER_READS[-1][1]
STORED_PUBLICATIONS_READ_PATH = '/api/v1/seo/content-distribution/publications'


def record_seo_media_manifest(native_root, module, manifest):
    """Audit immutable native bytes only; never infer/install database objects."""
    if module != 'seo':
        return
    names = ('app/seo_distribution_sources.py', 'app/seo_distribution_media.py',
             'app/api/seo_distribution_media.py', 'scripts/seo_distribution_media_schema.sql')
    for name in names:
        source = Path(native_root) / name
        manifest.setdefault('pilot_native_files', {})[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest['seo_media_schema'] = {
        'source': names[-1], 'sha256': manifest['pilot_native_files'][names[-1]],
        'target_schema': 'acceptance_seo', 'automatic_install': False,
        'database_status': 'not_inspected_by_manifest',
    }


def mount_seo_media_routes(app, module):
    """Retain actual native route classes/auth/dependencies; omit static shells."""
    if module != 'seo':
        return
    from fastapi import APIRouter
    from app.api.seo_distribution_media import router as native
    prefix = '/api/seo/distribution-media/variants'
    expected = {'drafts': (prefix, {'GET'}), 'preview': (prefix + '/{variant_id}', {'GET'}),
        'upload': (prefix + '/{variant_id}/assets', {'POST'}),
        'preview_asset': (prefix + '/{variant_id}/assets/{asset_id}', {'GET'}),
        'review': (prefix + '/{variant_id}/review', {'POST'})}
    selected = APIRouter()
    for name, (path, methods) in expected.items():
        matches = [route for route in native.routes if route.endpoint.__name__ == name
                   and route.path == path and route.methods == methods]
        if len(matches) != 1:
            raise RuntimeError('Exact reviewed native media route required')
        selected.routes.append(matches[0])
    app.include_router(selected)


def mount_exact_native_read(app, native, endpoint_name, path):
    """Expose one existing GET without recreating handler/auth dependencies."""
    matches = [route for route in native.routes if route.endpoint.__name__ == endpoint_name
               and route.path == path and route.methods == {'GET'}]
    if len(matches) != 1:
        raise RuntimeError('Exact native read route required')
    existing = [route for route in app.router.routes if getattr(route, 'path', None) == path
                and getattr(route, 'methods', None) == {'GET'}]
    if existing:
        if len(existing) != 1 or existing[0].endpoint is not matches[0].endpoint:
            raise RuntimeError('Conflicting native read route')
        return
    # include_router retains the original endpoint/class/dependencies while
    # attaching this application's dependency_overrides_provider. Raw append
    # would leave get_seo_session's primary alias outside the owned override.
    from fastapi import APIRouter
    selected = APIRouter()
    selected.routes.append(matches[0])
    app.include_router(selected)


def mount_seo_customer_reads(app, native, module):
    """Mount only the five stored-data GETs, never their adjacent writes."""
    if module != 'seo':
        return None
    # Validate the whole set before adding any of it. Keep original route class,
    # module/scope/auth dependencies and the owned session override provider.
    routes = []
    for name, path in CUSTOMER_READS:
        matches = [route for route in native.routes if route.endpoint.__name__ == name
                   and route.path == path and route.methods == {'GET'}]
        if len(matches) != 1:
            raise RuntimeError('Exact native customer read route required')
        routes.append(matches[0])
    for route in routes:
        mount_exact_native_read(app, native, route.endpoint.__name__, route.path)
    return routes[-1].endpoint


def readonly_publication_evidence(request, root, config, module, app, reader):
    """One owned pilot list exception; no publication/source/check admission.

    A bearer header is required here; actual JWT/current role/tenant/site checks
    still run in the original native route. Nothing authorizes a write/fetch.
    """
    if (module != 'seo' or config.get('production') is not False
            or config.get('platform') != 'linux-acceptance'
            or root != Path('/opt/gsnipers-distribution-acceptance/work/distribution-server-pilot-20261012')
            or config.get('root') != str(root) or config.get('ports') != PORTS
            or config.get('native_heads', {}).get('seo') != '3087e62f23e799fe82d279f79f698f0499bf3a27'
            or request.method != 'GET' or request.url.path != EVIDENCE_READ_PATH
            or request.scope.get('raw_path') != EVIDENCE_READ_PATH.encode('ascii')
            or not request.headers.get('authorization', '').startswith('Bearer ')
            or not request.headers['authorization'][7:].strip() or reader is None):
        return False
    registered = [route for route in app.router.routes if getattr(route, 'path', None) == EVIDENCE_READ_PATH
                  and getattr(route, 'methods', None) == {'GET'}]
    if len(registered) != 1 or registered[0].endpoint is not reader:
        return False
    pairs = list(request.query_params.multi_items())
    if len({key for key, _ in pairs}) != len(pairs):
        return False
    values = dict(pairs)
    if (values.get('tenant_id') != '15' or values.get('site_id') != '6'
            or set(values) - {'tenant_id', 'site_id', 'content_id', 'publication_id', 'page', 'page_size'}):
        return False
    for key in ('content_id', 'publication_id', 'page', 'page_size'):
        if key in values:
            value = values[key]
            if not value.isascii() or not value.isdecimal() or len(value) > 19 or value.startswith('0'):
                return False
            if not 1 <= int(value) <= ({'page': 10000, 'page_size': 100}.get(key, 2**63 - 1)):
                return False
    return True


def mount_stored_publications_read(app, native, module):
    """Keep the existing native stored-list route and owned dependency provider."""
    if module != 'seo':
        return None
    mount_exact_native_read(app, native, 'list_content_publications', STORED_PUBLICATIONS_READ_PATH)
    return next(route.endpoint for route in native.routes
                if route.endpoint.__name__ == 'list_content_publications'
                and route.path == STORED_PUBLICATIONS_READ_PATH and route.methods == {'GET'})


def readonly_stored_publications(request, root, config, module, app, reader):
    """Read this pilot's stored delivery records even after its mint permit ends.

    The native named JWT/module/tenant/site guards still run. This exception
    neither admits attempts/detail URLs nor authorizes any write or public fetch.
    """
    if (module != 'seo' or config.get('production') is not False
            or config.get('platform') != 'linux-acceptance'
            or root != Path('/opt/gsnipers-distribution-acceptance/work/distribution-server-pilot-20261012')
            or config.get('root') != str(root) or config.get('ports') != PORTS
            or config.get('native_heads', {}).get('seo') != '3087e62f23e799fe82d279f79f698f0499bf3a27'
            or request.method != 'GET' or request.url.path != STORED_PUBLICATIONS_READ_PATH
            or request.scope.get('raw_path') != STORED_PUBLICATIONS_READ_PATH.encode('ascii')
            or not request.headers.get('authorization', '').startswith('Bearer ')
            or not request.headers['authorization'][7:].strip() or reader is None):
        return False
    registered = [route for route in app.router.routes
                  if getattr(route, 'path', None) == STORED_PUBLICATIONS_READ_PATH
                  and getattr(route, 'methods', None) == {'GET'}]
    if len(registered) != 1 or registered[0].endpoint is not reader:
        return False
    pairs = list(request.query_params.multi_items())
    return (len(pairs) == 3 and len({key for key, _ in pairs}) == 3
            and dict(pairs) == {'tenant_id': '15', 'site_id': '6', 'content_id': '61'})


def prepare(config_path, module):
    config = read(config_path)
    root = owned(config['root'])
    if config_path.resolve() != root/'environment.json' or config['production'] is not False or config['ports']!=PORTS:
        raise RuntimeError('Owned non-production config required')
    from sqlalchemy.engine import make_url
    url = make_url(os.environ['DATABASE_URL'])
    if (url.host, url.port, url.username, url.database) != ('127.0.0.1', PORTS['pg'],
        'distribution_acceptance', 'distribution_acceptance_'+module) or url.query:
        raise RuntimeError('Refuse any non-acceptance database')
    if Path.cwd().resolve() != root or (root/'.env').exists():
        raise RuntimeError('Private cwd with no dotenv required')
    fallback = Path(config.get('dependency_fallback','C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/python'))
    if (root/'python-deps').is_dir(): sys.path.append(str(root/'python-deps'))
    if (fallback/'Lib/site-packages').is_dir(): sys.path.append(str(fallback/'Lib/site-packages'))
    elif fallback.is_dir(): sys.path.append(str(fallback))
    expected=config.get('native_heads',{}).get(module,HEADS[module])
    if expected not in REVIEWED_ACCEPTANCE_HEADS[module]:raise RuntimeError('Unreviewed acceptance native commit')
    default=HEADS[module]
    try:
        HEADS[module]=expected
        manifest = assemble(config['native_roots'][module], module)
    finally:HEADS[module]=default
    import app
    # Native api/__init__.py registers unrelated modules. Use a package path,
    # then load only reviewed native handlers, without executing that registry.
    package = types.ModuleType('app.api')
    package.__path__ = [str(Path(config['native_roots'][module])/'app/api'), str(Path(config['central_root'])/'app/api')]
    sys.modules['app.api'] = package
    app.api = package
    import app.security
    app.security.__path__.append(str(Path(config['central_root'])/'app/security'))
    from app import database
    schema = 'acceptance_'+module
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine(url, pool_pre_ping=True, hide_parameters=True, connect_args={'server_settings':{
        'search_path': schema, 'timezone':'UTC', 'lock_timeout': '5000', 'statement_timeout': '20000'}},
        execution_options={'schema_translate_map': {'public': schema}})
    database.engine = engine
    database.async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    from app import api_controls, api_metering
    api_controls.async_session_factory = database.async_session_factory
    api_metering.async_session_factory = database.async_session_factory
    for name in ('app/distribution_remote.py','app/distribution_remote_contract.py',
                 'app/api/distribution_remote.py','app/api/auth.py',
                 'app/distribution_api_contract.py','app/distribution_api_orders.py',
                 'app/distribution_pairing.py','app/distribution_pairing_contract.py',
                 'app/api/distribution_pairing.py','scripts/distribution_device_pairing_schema.sql',
                 'docs/fixtures/distribution-device-pairing-v1.json','scripts/distribution_remote_schema.sql'):
        source=Path(config['central_root'])/name
        if source.exists(): manifest.setdefault('central_files',{})[name]=hashlib.sha256(source.read_bytes()).hexdigest()
    for name in ('app/api/seo_automation_projects.py','app/api/seo_onsite_ai.py','app/seo_demo_source.py'):
        source=Path(config['native_roots'][module])/name
        if source.exists(): manifest.setdefault('pilot_native_files',{})[name]=hashlib.sha256(source.read_bytes()).hexdigest()
    record_seo_media_manifest(config['native_roots'][module], module, manifest)
    for file in ('distribution_server_pilot_environment.py', 'distribution_server_pilot_native.py','distribution_server_pilot_configure.py',
                 'distribution_single_publication_gate.py'):
        manifest.setdefault('acceptance_files', {})[file] = hashlib.sha256((Path(__file__).parent/file).read_bytes()).hexdigest()
    linux_runner=Path(__file__).parent/'distribution_linux_acceptance.py'
    if linux_runner.exists():
        manifest.setdefault('acceptance_files', {})[linux_runner.name]=hashlib.sha256(linux_runner.read_bytes()).hexdigest()
    static=Path(config['central_root'])/'app/static/distribution-acceptance'
    for file in static.glob('*'):
        manifest.setdefault('acceptance_files', {})['ui/'+file.name]=hashlib.sha256(file.read_bytes()).hexdigest()
    compiled=Path(config['central_root'])/'customer-workbench/dist/customer-workbench'
    for name in ('index.html','app.js','app.css','release-manifest.json'):
        source=compiled/name
        if source.exists(): manifest.setdefault('pilot_compiled_files',{})[name]=hashlib.sha256(source.read_bytes()).hexdigest()
    manifest.update(environment_root=str(root), module=module, port=PORTS[module], schema=schema,
        automaticSubmit=False, publicationVerified=False, production=False,
        planner_provider='deterministic in-process simulator; no external provider call')
    manifest['dependency_fallback'] = str(fallback)
    if (root/'python-deps').is_dir():
        files = {str(file.relative_to(root/'python-deps')).replace('\\','/'):hashlib.sha256(file.read_bytes()).hexdigest()
            for file in sorted((root/'python-deps').rglob('*')) if file.is_file() and '__pycache__' not in file.parts}
        manifest['acceptance_python_dependencies'] = {'files':len(files),
            'tree_sha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),
            'packages':{'python-docx':'1.2.0','lxml':'5.3.2'},'python':'3.11'}
    return root, config, engine, database.async_session_factory, manifest


def install_transport_guard():
    """Intercept the managed planner only; reject every other overseas transport."""
    import httpx
    original = httpx.AsyncHTTPTransport.handle_async_request
    async def guarded(self, request):
        if request.url.host == 'api.deepseek.com' and request.url.path.endswith('/chat/completions'):
            body = json.loads(request.content)
            if set(body) != {'model','messages','response_format','temperature','stream','max_tokens'} or body['max_tokens'] != 1500:
                raise RuntimeError('Only bounded distribution planning simulator supported')
            snapshot = json.loads(body['messages'][-1]['content'])
            result = {'items': [{'queue_id': item['queue_id'], 'at': item['earliest_at']} for item in snapshot['items']]}
            return httpx.Response(200, json={'id': 'acceptance-local-planner',
                'choices': [{'message': {'content': json.dumps(result)}}],
                'usage': {'prompt_tokens': 0, 'completion_tokens': 0}}, request=request)
        if request.url.host not in {'127.0.0.1', 'localhost'}:
            raise RuntimeError('Acceptance external transport disabled')
        return await original(self, request)
    httpx.AsyncHTTPTransport.handle_async_request = guarded


async def initialize(root, config, engine, sessions, module, manifest):
    import app.models
    from app.database import Base
    from app.models.user import User
    from app.models.role import Role
    from app.security.auth import hash_password
    from sqlalchemy import text, Integer
    from sqlalchemy.schema import CreateTable
    common = {'tenants', 'tenant_modules', 'roles', 'users'}
    tables = {table.name: table for table in Base.metadata.tables.values()
        if table.name in common or table.name.startswith(module+'_')}
    async with engine.begin() as db:
        await db.execute(text('CREATE SCHEMA acceptance_'+module))
        # Native table contracts are kept; omitted FKs match the established
        # isolated native fixtures, never a candidate production migration.
        for table in tables.values():
            await db.execute(CreateTable(table, include_foreign_key_constraints=[]))
        raw = (await db.get_raw_connection()).driver_connection
        if module == 'geo':
            await raw.execute('CREATE TABLE public.demo_tenant_bindings (tenant_id bigint,demo_tenant_id bigint,dataset_key varchar(64),dataset_version varchar(40),status varchar(16),version integer)')
        native = Path(config['native_roots'][module])
        central = Path(config['central_root'])
        sources = [native/'scripts/api_metering_schema.sql', native/'scripts/api_controls_schema.sql']
        sources += [central/('scripts/distribution_'+name+'_schema.sql') for name in
                    ('control','scheduling','publication','queue','planning','execution','capability_registration')]
        result_sql = native/('scripts/'+module+'_distribution_results_schema.sql')
        if result_sql.exists(): sources.append(result_sql)
        for source in sources:
            await raw.execute(source.read_text(encoding='utf-8-sig').replace('BEGIN;', '').replace('COMMIT;', ''))
        await raw.execute('CREATE TABLE acceptance_handoff_events(task_id uuid,sequence integer,tenant_id bigint,module varchar(3),scope_id bigint,variant_id bigint,source_revision text,status text,code text,at bigint,PRIMARY KEY(task_id,sequence))')
    report = {'snapshot': None, 'collections': {}, 'ignored_fields': {}, 'production_mutations': False}
    snapshot_path = root/'customer-snapshot.json'
    if snapshot_path.exists():
        data = snapshot_path.read_bytes()
        snapshot = json.loads(data)
        if snapshot.get('snapshotVersion') != 1:
            raise RuntimeError('Unsupported customer snapshot version')
        report['snapshot'] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'capturedAt': snapshot['capturedAt'], 'source': 'read-only customer snapshot'}
        async with engine.begin() as db:
            for name, rows in snapshot['collections'].items():
                if name not in tables: continue
                table = tables[name]
                report['collections'][name] = len(rows)
                ignored = set()
                for row in rows:
                    if any(key in row for key in ('password_hash','credentials','config','api_key','access_token')):
                        raise RuntimeError('Disallowed credential-bearing snapshot column')
                    values = {}
                    for key, value in row.items():
                        if key not in table.c:
                            ignored.add(key); continue
                        column = table.c[key]
                        if value is not None:
                            try: kind = column.type.python_type
                            except NotImplementedError: kind = None
                            if kind is datetime:
                                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                if value.tzinfo and not getattr(column.type, 'timezone', False):
                                    value = value.astimezone(timezone.utc).replace(tzinfo=None)
                            elif kind is date: value = date.fromisoformat(value)
                            elif kind is bytes: value = base64.b64decode(value, validate=True)
                        values[key] = value
                    await db.execute(table.insert().values(**values))
                if ignored: report['ignored_fields'][name] = sorted(ignored)
    private = read(root/'secrets.json')
    async with sessions.begin() as db:
        permissions = {module+'.content': 'edit', module+'.assets': 'edit', module+'.site': 'edit'}
        if module=='seo': permissions['seo.keywords']='view'
        if module=='geo': permissions['geo.diagnosis']='view'
        customer_role='独立验收客户只读'
        if module=='geo':
            from app.permissions import CUSTOMER_ROLE
            customer_role=CUSTOMER_ROLE
        db.add_all([Role(id=100005, name='独立验收顾问', permissions=permissions),
            Role(id=100006, name='独立验收管理员', permissions={**permissions,'settings.accounts':'edit','settings.customers':'edit'}),
            Role(id=100010, name=customer_role, permissions={module+'.content':'view',module+'.assets':'view',module+'.site':'view',**({'geo.diagnosis':'view'} if module=='geo' else {})})])
        for ident, name, role, tenant in [(100007,'acceptance-advisor',100005,None),
            (100008,'acceptance-admin',100006,None),(100012,'acceptance-reviewer',100005,None),
            (100001,'acceptance-customer-1',100010,1),(100015,'acceptance-customer-15',100010,15),
            (100099,'acceptance-foreign-customer',100010,999999)]:
            db.add(User(id=ident, username=name, display_name=name, password_hash=hash_password(private['password']),
                role_id=role, tenant_id=tenant, is_active=True))
    # Imported explicit IDs must not make later native inserts collide.
    async with engine.begin() as db:
        for table in tables.values():
            if 'id' in table.c and table.c.id.primary_key and isinstance(table.c.id.type, Integer):
                qualified = manifest['schema']+'.'+table.name
                await db.execute(text("SELECT setval(pg_get_serial_sequence(:name,'id'), COALESCE((SELECT max(id) FROM "+qualified+"),1), true)"), {'name':qualified})
    write(root/(module+'-import-report.json'), report)
    write(root/(module+'-manifest.json'), manifest)


async def native_schema(root,config,engine,module):
    if module!='seo': raise RuntimeError('Only reviewed SEO 0105 migration supported here')
    from sqlalchemy import text
    import importlib.util
    source=Path(config['native_roots'][module])/'migrations/versions/20261007_0105_seo_content_confirmations.py'
    async with engine.begin() as db:
        exists=await db.scalar(text("SELECT to_regclass(current_schema()||'.alembic_version') IS NOT NULL"))
        if exists:
            revision=await db.scalar(text('SELECT version_num FROM alembic_version'))
            if revision=='0105_seo_content_confirmations':
                proof=read(root/'seo-native-schema.json')
                if not proof.get('actual_native_upgrade_executed') or proof.get('source_sha256')!=hashlib.sha256(source.read_bytes()).hexdigest():
                    raise RuntimeError('Native migration completion proof unavailable')
                return
            raise RuntimeError('Unexpected acceptance migration revision')
        for name in ('seo_content_confirmations','seo_site_advisor_assignments'):
            if await db.scalar(text('SELECT count(*) FROM '+name)):
                raise RuntimeError('Refuse to replace any populated native gate table')
        # These two empty fixture tables are replaced by the actual native DDL,
        # including native foreign keys, checks and indexes.
        await db.execute(text('DROP TABLE seo_content_confirmations'))
        await db.execute(text('DROP TABLE seo_site_advisor_assignments'))
        def migrate(connection):
            from alembic.migration import MigrationContext
            from alembic.operations import Operations
            spec=importlib.util.spec_from_file_location('acceptance_native_0105',source)
            migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
            if migration.revision!='0105_seo_content_confirmations':raise RuntimeError('Native revision changed')
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
        await db.run_sync(migrate)
        await db.execute(text('CREATE TABLE alembic_version(version_num varchar(40) PRIMARY KEY)'))
        await db.execute(text("INSERT INTO alembic_version VALUES('0105_seo_content_confirmations')"))
    write(root/'seo-native-schema.json',{'revision':'0105_seo_content_confirmations',
        'actual_native_upgrade_executed':True,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'baseline':'isolated native ORM module tables; not a production Alembic upgrade chain',
        'productionDDL':False})


async def pilot_schema(root,config,engine,module):
    """Reviewed new tables in the exact owned schema; never production DDL."""
    from sqlalchemy import text
    source=Path(config['central_root'])/'scripts/distribution_remote_schema.sql'
    if not source.is_file(): raise RuntimeError('Frozen remote schema required')
    async with engine.begin() as db:
        if await db.scalar(text('SELECT current_schema()'))!='acceptance_'+module:
            raise RuntimeError('Owned pilot schema required')
        raw=(await db.get_raw_connection()).driver_connection
        await raw.execute(source.read_text(encoding='utf-8'))
        if module=='seo':
            await db.execute(text("UPDATE roles SET permissions=permissions||jsonb_build_object('seo.keywords','view') WHERE id IN (100005,100006)"))
    write(root/(module+'-remote-schema.json'),{'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'actual_schema_executed':True,'schema':'acceptance_'+module,'pg_port':PORTS['pg'],
        'productionDDL':False,'test_role_keyword_view':module=='seo'})


def application(root, config, sessions, module, manifest):
    from fastapi import FastAPI, APIRouter, Depends, HTTPException
    from fastapi.responses import HTMLResponse
    from app.database import get_session
    from app.security.auth import require_auth
    from app.api.distribution import router
    from app.api.auth import router as auth_router
    app = FastAPI(title='Independent distribution acceptance '+module)
    evidence_reader = None
    stored_publications_reader = None
    @app.on_event('startup')
    async def metadata_registration():
        from app.api_controls import register_runtime
        await register_runtime(module)
    async def database():
        async with sessions() as db: yield db
    app.dependency_overrides[get_session] = database
    app.include_router(router)
    import distribution_single_publication_gate as single_publication
    single_publication.mount_task_wrapper(app, root, config, module)
    for route in auth_router.routes:
        if route.endpoint.__name__ in {'login','me','logout'}: app.router.routes.append(route)
    # Mount the reviewed real modules handler, not a generated auth/scope fixture.
    # Native login/me/security keep their frozen source and the same owned DB.
    if module=='seo':
        import importlib.util
        auth_source=Path(config['central_root'])/'app/api/auth.py'
        spec=importlib.util.spec_from_file_location('app.api.server_pilot_modules_auth',auth_source)
        modules_auth=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modules_auth)
        # The older native auth list omits module; this existing central handler
        # is the real permission/entitlement-filtered product read contract.
        mount_exact_native_read(app, modules_auth.router, 'list_tenants', '/api/v1/auth/tenants')
        @app.get('/api/v1/auth/modules')
        async def seo_native_modules(ctx=Depends(require_auth),db=Depends(get_session)):
            result=await modules_auth.list_my_modules(ctx=ctx,session=db)
            # A global admin's production catalogue also permits SEM settings.
            # This separate native unit does not serve SEM or GEO, so its login
            # must not offer those unavailable execution modules.
            result['modules']=[row if row['module_code']=='seo' else {
                **row,'available':False,'status':'not_in_acceptance','tenant_count':0}
                for row in result['modules']]
            return result
    else:
        # The frozen GEO module has its own older scope interface. Build its
        # acceptance catalogue from actual native entitlements, without replacing
        # shared authentication or importing incompatible SEO scope functions.
        from app.models import TenantModule
        from app.module_scope import module_is_available
        from sqlalchemy import select
        @app.get('/api/v1/auth/modules')
        async def geo_native_modules(ctx=Depends(require_auth),db=Depends(get_session)):
            query=select(TenantModule).where(TenantModule.module_code=='geo')
            if ctx.tenant_id is not None: query=query.where(TenantModule.tenant_id==ctx.tenant_id)
            rows=list(await db.scalars(query))
            permitted=ctx.can_view('geo.assets','geo.content','geo.diagnosis')
            available=[row for row in rows if module_is_available(row)]
            count=len(available) if permitted else 0
            result=[]
            for code in ('sem','seo','geo'):
                active=code=='geo' and permitted and (ctx.tenant_id is None or bool(available))
                row=rows[0] if code=='geo' and ctx.tenant_id is not None and rows else None
                result.append({'module_code':code,'status':row.status if row else 'active' if active else 'no_permission',
                    'available':bool(active),'expires_at':row.expires_at.isoformat() if row and row.expires_at else None,
                    'tenant_count':count if code=='geo' else 0})
            return {'tenant_id':ctx.tenant_id,'modules':result}
    if module == 'seo':
        from app.api.seo import router as native
        names = {'upsert_advisor_assignment','list_advisor_assignments','create_content_confirmation',
            'get_content_delivery','get_content_review_history','save_distribution_variant',
            'adapt_content_distribution','review_distribution_variant','decide_content_review',
            'create_content_asset','list_content_assets','submit_content_review','update_content_asset',
            'list_distribution_variants','list_distribution_connections','create_distribution_connection'}
        names.update({'projects','advisor_tasks'})
        # Read the actual native publication delivery model; no write handler.
        names.add('list_content_publications')
        selected = APIRouter()
        for route in native.routes:
            if route.endpoint.__name__ in names: selected.routes.append(route)
        app.include_router(selected)
        mount_seo_media_routes(app, module)
        evidence_reader = mount_seo_customer_reads(app, native, module)
        stored_publications_reader = mount_stored_publications_read(app, native, module)
        from app.api.customer_modules import seo_sites_router
        mount_exact_native_read(app, seo_sites_router, 'list_seo_workbench_sites',
                                '/api/v1/seo/workbench/sites')
    else:
        from app.geo.project_routes import geo_projects_router
        for route in geo_projects_router.routes:
            if '/service-plan/run' not in route.path: app.router.routes.append(route)
        from app.geo.content.routes import router as native
        names = {'list_content_tasks','get_task','patch_task','submit_task_review',
            'decide_task_review','update_variant','save_article','check_task','lint_task_article',
            'verify_fact','preview_manual_channel_finalization','finalize_manual_channel',
            'create_task','create_variants'}
        selected = APIRouter()
        for route in native.routes:
            if route.endpoint.__name__ in names: selected.routes.append(route)
        app.include_router(selected,prefix='/api/v1/geo')
    @app.middleware('http')
    async def no_publish(request, call_next):
        from fastapi.responses import JSONResponse
        import distribution_single_publication_gate as single
        payload = None
        protected_post = request.method == 'POST' and (
            request.url.path.rstrip('/').endswith('/tasks')
            or any(part in request.url.path for part in ('/publication-', '/publications', '/push')))
        if protected_post:
            try:
                payload = await single.request_payload(request)
            except HTTPException:
                return JSONResponse(status_code=403, content={'detail':'Acceptance formal publication disabled'},
                                    headers={'Cache-Control':'no-store'})
        device_path = request.url.path.startswith(('/api/distribution/v1/device/',
            '/api/distribution/capabilities/v1/device/', '/api/distribution/handoff/v1/device/',
            '/api/distribution/v1/remote/device/')) or request.url.path == '/api/distribution/v1/device-pairings/claim'
        if request.method not in {'GET','HEAD','OPTIONS'} and not device_path and request.url.path != '/api/v1/auth/login':
            from fastapi.security import HTTPAuthorizationCredentials
            value = request.headers.get('authorization','')
            if not value.startswith('Bearer '):
                return JSONResponse(status_code=401, content={'detail':'Named local login required'})
            try:
                async with sessions() as db:
                    ctx = await require_auth(bearer=HTTPAuthorizationCredentials(scheme='Bearer',credentials=value[7:]),
                        header_key=None,key=None,session=db)
                import re
                native_customer_review=False
                if module=='geo' and request.method=='POST' and re.fullmatch(r'/api/v1/geo/content-tasks/[1-9][0-9]*/review',request.url.path):
                    from app.geo.content.review import is_tenant_customer_reviewer
                    native_customer_review=is_tenant_customer_reviewer(ctx)
                if not native_customer_review and not ctx.can_edit(module+'.content',module+'.assets',module+'.site','settings.accounts'):
                    return JSONResponse(status_code=403, content={'detail':'Acceptance customer is read-only'})
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code,content={'detail':'Local login unavailable'})
        if (single.publication_request(request, payload)
                and not readonly_publication_evidence(request, root, config, module, app, evidence_reader)
                and not readonly_stored_publications(request, root, config, module, app, stored_publications_reader)):
            try:
                await single.authorize(request, root, config, sessions, module, payload)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={'detail':'Acceptance single publication not authorized'},
                                    headers={'Cache-Control':'no-store'})
        response=await call_next(request)
        delay_path=root/('ui-delay-'+module+'.json')
        if request.url.path=='/acceptance/original' and delay_path.exists():
            delay=read(delay_path)
            if delay.get('remaining',0)>0:
                milliseconds=delay.get('delay_ms',0)
                if type(milliseconds) is not int or not 0<=milliseconds<=5000:
                    raise RuntimeError('Bounded acceptance UI delay required')
                delay['remaining']-=1;delay['actual_response_status']=response.status_code
                write(delay_path,delay)
                await asyncio.sleep(milliseconds/1000)
        response.headers['Cache-Control']='no-store'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'"
        return response
    @app.get('/acceptance/health')
    async def health():
        from sqlalchemy import text
        async with sessions() as db: await db.execute(text('SELECT 1'))
        return {'running':True, **manifest}
    @app.get('/acceptance/routes')
    async def routes(ctx=Depends(require_auth)):
        if not ctx.can_edit('settings.accounts'): raise HTTPException(403,'Admin only')
        return {'module':module,'routes':[{'path':r.path,'methods':sorted(r.methods)} for r in app.routes if hasattr(r,'methods')]}
    @app.get('/acceptance/context')
    async def context(ctx=Depends(require_auth),db=Depends(get_session)):
        from app.module_scope import ensure_module_access
        public=read(root/(module+'-pairing.json'))
        await ensure_module_access(db,ctx,public['scope']['tenant_id'],module)
        local_master=None
        if module=='geo' and (root/'geo-derived-task.json').exists():
            pointer=read(root/'geo-derived-task.json')
            from app.models import GeoContentTask
            row=await db.get(GeoContentTask,pointer['task_id'])
            if not row or row.tenant_id!=public['scope']['tenant_id'] or row.business_id!=13 or pointer['scope']!=public['scope']:
                raise HTTPException(403,'Local derived task scope mismatch')
            local_master=row.id
        return {'module':module,'scope':public['scope'],'bindingIds':public['bindingIds'],
            'actorId':ctx.user_id,'actorName':ctx.username,'canEdit':ctx.can_edit(module+'.content'),
            'originalMasterId':60 if module=='seo' else 12,'originalVariantId':1 if module=='seo' else 2,
            'localMasterId':local_master,
            'publicationVerified':False,'plannerSimulation':True}
    @app.get('/acceptance/original')
    async def original(ctx=Depends(require_auth),db=Depends(get_session)):
        from app.module_scope import ensure_module_access
        public=read(root/(module+'-pairing.json'));scope=public['scope']
        await ensure_module_access(db,ctx,scope['tenant_id'],module)
        if not ctx.can_view(module+'.content'):raise HTTPException(403,'Content permission required')
        if module=='seo':
            from app.models.seo import SeoContentAsset,SeoDistributionVariant
            master=await db.get(SeoContentAsset,60);variant=await db.get(SeoDistributionVariant,1)
            if not master or master.tenant_id!=scope['tenant_id'] or master.site_id!=scope['scope_id'] or variant.content_asset_id!=master.id:
                raise HTTPException(404,'Original source unavailable')
            return {'masterId':master.id,'variantId':variant.id,'title':variant.title,'body':variant.content,
                'keywordIds':master.keyword_ids or [master.keyword_id],'version':master.version_count,
                'status':master.status,'platform':variant.platform_code,'originalOnly':True,'executionAuthority':False}
        from app.models import GeoContentTask,GeoArticleVersion
        task=await db.get(GeoContentTask,12);article=await db.get(GeoArticleVersion,17)
        if not task or task.tenant_id!=scope['tenant_id'] or article.task_id!=task.id:raise HTTPException(404,'Original source unavailable')
        return {'masterId':task.id,'articleId':article.id,'title':article.title,'body':article.body_markdown,
            'version':article.version_no,'status':task.status,'reviewStatus':task.review_status,
            'originalOnly':True,'executionAuthority':False}
    @app.get('/acceptance/handoff-results')
    async def customer_results(tenant_id:int,scope_id:int,ctx=Depends(require_auth),db=Depends(get_session)):
        from sqlalchemy import text
        from app.module_scope import ensure_module_access
        await ensure_module_access(db,ctx,tenant_id,module)
        if not ctx.can_view(module+'.content'): raise HTTPException(403,'Content read permission required')
        table = 'seo_sites' if module=='seo' else 'geo_projects'
        scope = (await db.execute(text('SELECT tenant_id,status FROM '+table+' WHERE id=:id'),{'id':scope_id})).mappings().one_or_none()
        if not scope or scope['tenant_id']!=tenant_id: raise HTTPException(404,'Project unavailable')
        rows = (await db.execute(text('SELECT task_id,sequence,variant_id,source_revision,status,code,at FROM acceptance_handoff_events WHERE module=:module AND tenant_id=:tenant AND scope_id=:scope ORDER BY at DESC,sequence DESC LIMIT 100'),
            {'module':module,'tenant':tenant_id,'scope':scope_id})).mappings().all()
        return {'module':module,'tenant_id':tenant_id,'scope_id':scope_id,'items':[dict(row) for row in rows],
            'publicationVerified':False,'result_type':'isolated acceptance handoff ledger; no native published status'}
    @app.get('/acceptance/')
    async def page():
        from fastapi.responses import FileResponse
        return FileResponse(Path(config['central_root'])/'app/static/distribution-acceptance/index.html')
    @app.get('/acceptance/app.js')
    async def page_script():
        from fastapi.responses import FileResponse
        return FileResponse(Path(config['central_root'])/'app/static/distribution-acceptance/app.js',media_type='text/javascript')
    @app.get('/acceptance/style.css')
    async def page_style():
        from fastapi.responses import FileResponse
        return FileResponse(Path(config['central_root'])/'app/static/distribution-acceptance/style.css',media_type='text/css')
    @app.get('/customer-workbench/')
    @app.get('/customer-workbench/{name}')
    async def compiled_advisor(name:str='index.html'):
        from fastapi.responses import FileResponse
        allowed={'index.html':'text/html','app.js':'text/javascript',
                 'app.css':'text/css','release-manifest.json':'application/json'}
        if name not in allowed: raise HTTPException(404,'Pilot asset unavailable')
        source=Path(config['central_root'])/'customer-workbench/dist/customer-workbench'/name
        if not source.is_file(): raise HTTPException(503,'Pilot standard build unavailable')
        return FileResponse(source,media_type=allowed[name])
    return app


async def work(sessions, module):
    from app.api_controls import register_runtime
    await register_runtime(module)
    from app.distribution_queue import run_once as queue
    from app.distribution_planning import run_once as planning
    from app.distribution_execution import run_once as dispatch
    from sqlalchemy import text
    while True:
        await queue(sessions, module=module)
        await planning(sessions, module=module)
        await dispatch(sessions, module=module)
        async with sessions.begin() as db:
            await db.execute(text("INSERT INTO acceptance_handoff_events SELECT id,receipt_sequence,tenant_id,module,scope_id,variant_id,source_revision,status,receipt->>'code',receipt_at FROM distribution_tasks WHERE module=:module AND action='handoff' AND receipt IS NOT NULL ON CONFLICT DO NOTHING"), {'module':module})
        await asyncio.sleep(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--module', choices=('seo','geo'), required=True)
    parser.add_argument('action', choices=('initialize','native-schema','pilot-schema','serve','worker'))
    args = parser.parse_args()
    root, config, engine, sessions, manifest = prepare(args.config, args.module)
    install_transport_guard()
    if args.action == 'initialize':
        asyncio.run(initialize(root, config, engine, sessions, args.module, manifest))
    elif args.action=='native-schema':
        asyncio.run(native_schema(root,config,engine,args.module))
    elif args.action=='pilot-schema':
        asyncio.run(pilot_schema(root,config,engine,args.module))
    elif args.action == 'serve':
        import uvicorn
        uvicorn.run(application(root, config, sessions, args.module, manifest), host='127.0.0.1',
            port=PORTS[args.module], ssl_keyfile=str(root/'loopback.key'), ssl_certfile=str(root/'loopback.pem'),
            access_log=False, log_level='warning')
    else: asyncio.run(work(sessions, args.module))


if __name__ == '__main__': main()


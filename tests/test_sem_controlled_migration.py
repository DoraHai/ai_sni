"""Controlled runner tests; native tests create only disposable loopback databases."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
import ssl
from pathlib import Path
import subprocess
import sys
import uuid
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("controlled_test", ROOT / 'ops/sem-task-migration/controlled.py')
ctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctl)


def approval():
    now = datetime.now(timezone.utc)
    a = {k: 'a' * 40 for k in ('checkout_commit', 'seo_release_commit', 'seo_rollback_commit')}
    a.update({k: 'b' * 64 for k in ('manifest_sha256','baseline_sha256','schema_sha256',
                                  'seo_release_sha256','seo_rollback_sha256','ca_bundle_sha256')})
    a.update({k: 'test-evidence' for k in ('change_id','operator','reviewer','backup_evidence',
             'restore_evidence','pause_evidence','seo_compatibility_evidence','schema_review_evidence')})
    a.update(confirmation='MIGRATE_SEM_TASKS_0095', schema='public', start_revision=ctl.bundle.START,
             target_revision=ctl.bundle.TARGET, application_role='sem_test',
             not_before=(now-timedelta(minutes=1)).isoformat(), expires_at=(now+timedelta(minutes=10)).isoformat(),
             database=dict(host='127.0.0.1', port=55449, name='test-only', role='sem_test',
                           server_address='127.0.0.1', server_port=55449))
    return a


@pytest.mark.parametrize('key,value', [
    ('target_revision','head'), ('start_revision','0093_seo_qa'), ('schema','other'),
    ('confirmation','DEPLOY_SEM'), ('checkout_commit','main'), ('manifest_sha256',''),
    ('ca_bundle_sha256',''), ('ca_bundle_sha256','A'*64),
    ('backup_evidence',''), ('restore_evidence','UNKNOWN'), ('pause_evidence','TBD'),
    ('application_role','different_role'), ('expires_at','2000-01-01T00:00:00+00:00'),
    ('not_before','2099-01-01T00:00:00+00:00'), ('expires_at','2099-01-01T00:00:00'),
])
def test_refuses_unapproved_contract(key,value):
    a=approval(); a[key]=value
    with pytest.raises((ValueError, KeyError)):
        ctl.validate_approval(a)


def test_accepts_complete_attestation_not_proof_of_external_actions():
    ctl.validate_approval(approval())


def test_baseline_digest_cannot_be_silently_replaced(tmp_path):
    p=tmp_path/'baseline.json'; p.write_text('{}')
    with pytest.raises(ValueError): ctl.checked_json(p,'0'*64)


def test_checkout_must_match_and_be_clean(monkeypatch):
    monkeypatch.setattr(ctl.subprocess,'check_output',lambda *a,**k:b'wrong')
    with pytest.raises(ValueError): ctl.verify_checkout('a'*40)


@pytest.mark.parametrize('commit_error',[False,True])
def test_commit_acknowledgement_is_not_assumed(monkeypatch,commit_error):
    import sqlalchemy.ext.asyncio as sa_async
    class Tx:
        async def __aenter__(self): return object()
        async def __aexit__(self,*args):
            if commit_error: raise ConnectionError('simulated lost commit reply')
    class Engine:
        def begin(self): return Tx()
        async def dispose(self): pass
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    def create_engine(*args, **kwargs):
        assert kwargs['connect_args']['ssl'] is tls
        assert tls.check_hostname and tls.verify_mode == ssl.CERT_REQUIRED
        return Engine()
    monkeypatch.setattr(sa_async,'create_async_engine',create_engine)
    monkeypatch.setattr(ctl,'migrate_transaction',AsyncMock())
    phases=[]
    if commit_error:
        with pytest.raises(ConnectionError): asyncio.run(ctl.apply(approval(),{},None,None,phases.append,tls))
        assert phases==['transaction_started','ready_to_commit']
    else:
        asyncio.run(ctl.apply(approval(),{},None,None,phases.append,tls))
        assert phases==['transaction_started','ready_to_commit','commit_acknowledged']


def test_credentials_are_not_taken_from_application_environment():
    source=(ROOT/'ops/sem-task-migration/controlled.py').read_text(encoding='utf-8')
    assert 'os.environ' not in source
    assert 'os.O_NOFOLLOW' in source and 'ssl.PROTOCOL_TLS_CLIENT' in source
    assert 'ssl.create_default_context' not in source
    assert 'load_default_certs' not in source
    assert 'choices=["fingerprint", "check", "apply"]' in source
    assert 'command.upgrade(cfg, bundle.TARGET)' in source
    assert 'command.stamp' not in source and 'command.downgrade' not in source


def test_ca_digest_is_mandatory_in_approval():
    a = approval(); del a['ca_bundle_sha256']
    with pytest.raises(KeyError): ctl.validate_approval(a)


@pytest.mark.parametrize('mode', ['check', 'apply'])
def test_cli_requires_ca_before_loading_credentials(monkeypatch, mode):
    monkeypatch.setattr(sys, 'argv', ['controlled.py', mode, '--baseline', 'unused',
                                    '--approval', 'unused', '--approval-sha256', 'a'*64,
                                    '--bundle', 'unused'])
    def unexpected(*args): pytest.fail('Must refuse before reading credentials/approval')
    monkeypatch.setattr(ctl, 'credential_url', unexpected)
    monkeypatch.setattr(ctl, 'checked_json', unexpected)
    with pytest.raises(ValueError, match='CA file required'):
        ctl.main()


@pytest.fixture
def tls_material(tmp_path):
    # Ephemeral test-only CA/server key. Handshakes below use memory BIOs, no network/DB.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    now = datetime.now(timezone.utc)
    def cert(subject, issuer, public_key, signer, ca):
        builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
                   .public_key(public_key).serial_number(x509.random_serial_number())
                   .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
        if not ca:
            builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName('db.test')]), False)
        return builder.sign(signer, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Ephemeral test CA')])
    ca = cert(name, name, ca_key.public_key(), ca_key, True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = cert(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'db.test')]), name,
                key.public_key(), ca_key, False)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = cert(name, name, other_key.public_key(), other_key, True)
    ca_file = tmp_path/'ca.pem'; ca_file.write_bytes(ca)
    cert_file = tmp_path/'server.pem'; cert_file.write_bytes(leaf)
    key_file = tmp_path/'test-key.pem'
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert_file, key_file)
    return ca_file, server, other, leaf


def handshake(client_ctx, server_ctx, hostname):
    ci, co, si, so = (ssl.MemoryBIO() for _ in range(4))
    client = client_ctx.wrap_bio(ci, co, server_hostname=hostname)
    server = server_ctx.wrap_bio(si, so, server_side=True)
    done = [False, False]
    for _ in range(20):
        for i, peer in enumerate((client, server)):
            if not done[i]:
                try:
                    peer.do_handshake(); done[i] = True
                except ssl.SSLWantReadError:
                    pass
        si.write(co.read()); ci.write(so.read())
        if all(done): return
    pytest.fail('TLS handshake did not finish')


def test_approved_private_ca_and_hostname_handshake(tls_material, monkeypatch):
    ca, server, _, _ = tls_material
    monkeypatch.setenv('SSL_CERT_FILE', 'nonexistent-ambient-ca')
    ctx = ctl.tls_context(ca, ctl.sha(ca.read_bytes()))
    assert ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.cert_store_stats()['x509_ca'] == 1
    handshake(ctx, server, 'db.test')


@pytest.mark.parametrize('failure', ['wrong_ca', 'wrong_hostname'])
def test_tls_handshake_refuses_untrusted_server(tls_material, failure):
    ca, server, other, _ = tls_material
    if failure == 'wrong_ca': ca.write_bytes(other)
    ctx = ctl.tls_context(ca, ctl.sha(ca.read_bytes()))
    with pytest.raises(ssl.SSLCertVerificationError):
        handshake(ctx, server, 'wrong.test' if failure == 'wrong_hostname' else 'db.test')


@pytest.mark.parametrize('failure', ['digest', 'missing', 'corrupt', 'empty', 'oversize', 'leaf_only', 'private_key'])
def test_ca_file_refused_offline(tls_material, failure):
    ca, _, _, leaf = tls_material
    digest = ctl.sha(ca.read_bytes())
    if failure == 'missing': ca.unlink()
    elif failure == 'digest': ca.write_bytes(ca.read_bytes()+b'\n')
    else:
        raw = {'corrupt': b'-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----',
               'empty': b'', 'oversize': b'x'*(1024*1024+1), 'leaf_only': leaf,
               'private_key': ca.read_bytes()+b'\n-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----'}[failure]
        ca.write_bytes(raw); digest = ctl.sha(raw)
    with pytest.raises((ValueError, OSError)):
        ctl.tls_context(ca, digest)


@pytest.mark.parametrize('url',[
    'postgresql+asyncpg://sem_test:fake@other:55449/test-only',
    'postgresql+asyncpg://sem_test:fake@127.0.0.1:55449/other',
    'postgresql+asyncpg://other:fake@127.0.0.1:55449/test-only',
    'postgresql+asyncpg://sem_test@127.0.0.1:55449/test-only',
    'postgresql+asyncpg://sem_test:fake@127.0.0.1:55449/test-only?ssl=disable',
])
def test_connection_override_refused(url):
    with pytest.raises(ValueError): ctl.validate_url(url,approval())


@pytest.mark.skipif(os.name!='posix',reason='production adapter is POSIX-only')
def test_credential_file_permissions_and_links(tmp_path):
    p=tmp_path/'credential'
    p.write_text('postgresql+asyncpg://sem_test:fake@127.0.0.1:55449/test-only')
    p.chmod(0o644)
    with pytest.raises(ValueError): ctl.credential_url(p,approval())
    p.chmod(0o600)
    assert ctl.credential_url(p,approval()).username=='sem_test'
    link=tmp_path/'link'; link.symlink_to(p)
    with pytest.raises(OSError): ctl.credential_url(link,approval())


@pytest.fixture(scope='module')
def native_bundle(tmp_path_factory):
    url=os.environ.get('SEM_TASK_MIGRATION_TEST_DATABASE_URL')
    if not url: pytest.skip('explicit disposable loopback PostgreSQL required')
    ctl.bundle.validate_local_url(url,'sem_migration_test_'+'a'*32)
    dest=tmp_path_factory.mktemp('controlled-source')/'bundle'
    r=subprocess.run([sys.executable,'-I','-B',str(ROOT/'ops/sem-task-migration/bundle.py'),
                      'build',str(dest)],capture_output=True,text=True)
    assert r.returncode==0, r.stderr
    return dest


@pytest.mark.parametrize('scenario',['success','repeat','drift','wrong_revision','collision','after_create_failure','identity'])
def test_controlled_native_transaction(native_bundle,scenario):
    r=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve()),str(native_bundle),scenario],
                     capture_output=True,text=True,timeout=45)
    assert r.returncode==0,r.stdout+r.stderr
    assert 'controlled-native=passed' in r.stdout


async def native(path,scenario):
    from sqlalchemy import text, event
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    url=ctl.bundle.validate_local_url(os.environ['SEM_TASK_MIGRATION_TEST_DATABASE_URL'],
                                      'sem_migration_test_'+'a'*32)
    dbname='sem_controlled_test_'+uuid.uuid4().hex
    admin=create_async_engine(url,poolclass=NullPool,isolation_level='AUTOCOMMIT')
    created=False; engine=None
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{dbname}"'))
            created=True
        engine=create_async_engine(url.set(database=dbname),poolclass=NullPool,hide_parameters=True)
        async with engine.begin() as conn:
            await conn.execute(text('CREATE TABLE public.tenants(id BIGINT PRIMARY KEY, name TEXT)'))
            await conn.execute(text("INSERT INTO public.tenants VALUES (9007199254740993,'preserve')"))
            await conn.execute(text('CREATE TABLE public.alembic_version(version_num VARCHAR(32) PRIMARY KEY)'))
            await conn.execute(text("INSERT INTO public.alembic_version VALUES ('0094_seo_qa_batches')"))
        async with engine.begin() as conn:
            await conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            await conn.execute(text('SET LOCAL search_path=pg_catalog,public,pg_temp'))
            baseline=await ctl.snapshot(conn)
        a=approval(); a['database'].update(name=dbname,role=url.username,port=url.port,
                                          server_address=baseline['server_address'],server_port=baseline['server_port'])
        a['application_role']=url.username
        a['schema_sha256']=ctl.sha(ctl.canonical(ctl.structural(baseline)))
        ctl.validate_approval(a); ctl.checked_baseline(a,baseline)
        cfg=ctl.configuration(path)
        if scenario in ('drift','wrong_revision','collision'):
            async with engine.begin() as conn:
                sql={'drift':'ALTER TABLE public.tenants ADD COLUMN extra TEXT',
                     'wrong_revision':"UPDATE public.alembic_version SET version_num='0093_seo_qa'",
                     'collision':'CREATE SEQUENCE public.sem_tasks_id_seq'}[scenario]
                await conn.execute(text(sql))
        if scenario=='identity': a['database']['name']='wrong'
        if scenario=='after_create_failure':
            def fault(c,cu,statement,p,ctx,many):
                if statement.startswith('CREATE INDEX ix_sem_tasks_'):
                    raise RuntimeError('test-injected-after-create')
            event.listen(engine.sync_engine,'before_cursor_execute',fault)
        failed=False
        try:
            async with engine.begin() as conn:
                await ctl.migrate_transaction(conn,cfg,a,baseline)
        except (ValueError,RuntimeError) as e:
            failed=True
            if scenario=='after_create_failure': assert str(e)=='test-injected-after-create'
        assert failed == (scenario not in ('success','repeat'))
        if scenario=='repeat':
            with pytest.raises(ValueError):
                async with engine.begin() as conn: await ctl.migrate_transaction(conn,cfg,a,baseline)
        async with engine.connect() as conn:
            assert await conn.scalar(text('SELECT name FROM public.tenants'))=='preserve'
            assert await conn.scalar(text('SELECT version_num FROM public.alembic_version')) == (
                ctl.bundle.TARGET if not failed else '0093_seo_qa' if scenario=='wrong_revision' else ctl.bundle.START)
            assert bool(await conn.scalar(text("SELECT to_regclass('public.sem_tasks')"))) == (not failed)
            if scenario=='after_create_failure':
                for name in ctl.TARGETS:
                    assert await conn.scalar(text('SELECT to_regclass(:n)'),{'n':'public.'+name}) is None
            if not failed:
                await conn.execute(text('SET LOCAL search_path=pg_catalog,public,pg_temp'))
                after=await ctl.snapshot(conn)
                for category in ('columns','constraints','indexes'):
                    broken=deepcopy(after)
                    broken[category]=[r for r in broken[category] if r['relname']!='sem_tasks']
                    with pytest.raises(ValueError): ctl.postconditions(a,baseline,broken)
        print('controlled-native=passed')
    finally:
        if engine: await engine.dispose()
        if created:
            # This freshly-created random test DB is the ONLY drop target.
            assert dbname.startswith('sem_controlled_test_') and len(dbname)==52
            async with admin.connect() as conn: await conn.execute(text(f'DROP DATABASE "{dbname}"'))
        await admin.dispose()


if __name__=='__main__':
    asyncio.run(native(sys.argv[1],sys.argv[2]))

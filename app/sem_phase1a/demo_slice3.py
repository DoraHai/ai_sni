"""Generate slice3 evidence using only temporary synthetic SQLite databases."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from app.sem_phase0.contracts import LandingSubmission
from app.sem_phase0.store import SubmissionStore, ScopeDenied, RevisionConflict
from app.sem_phase1a.contracts import CreateRequest, RulingRequest, ApprovalRequest, ApplyRequest
from app.sem_phase1a.principals import LocalGrantPrincipalAdapter, SessionIdentity
from app.sem_phase1a.service import ShadowService
from app.sem_phase1a.sources import FIXTURES


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='sem-slice3-') as temp:
        root = Path(temp)
        auth_path = root / 'auth.sqlite'
        with closing(sqlite3.connect(auth_path)) as db, db:
            db.executescript("""
                CREATE TABLE tenants(id INTEGER PRIMARY KEY);
                CREATE TABLE users(id INTEGER PRIMARY KEY,is_active INTEGER,locked_until TEXT,tenant_id INTEGER,role TEXT);
                CREATE TABLE advisor_tenant_grants(id INTEGER PRIMARY KEY,user_id INTEGER,tenant_id INTEGER,revoked_at TEXT);
                CREATE TABLE tenant_modules(tenant_id INTEGER,module_code TEXT,status TEXT,expires_at TEXT);
                CREATE TABLE baidu_accounts(id INTEGER PRIMARY KEY,tenant_id INTEGER,status TEXT);
                CREATE TABLE sem_phase1a_account_grants(user_id INTEGER,tenant_id INTEGER,account_id INTEGER,advisor_grant_id INTEGER,revoked_at TEXT);
                INSERT INTO tenants VALUES(101);
                INSERT INTO users VALUES(1,1,NULL,NULL,'advisor'),(2,1,NULL,101,'customer');
                INSERT INTO advisor_tenant_grants VALUES(10,1,101,NULL);
                INSERT INTO tenant_modules VALUES(101,'sem','active',NULL);
                INSERT INTO baidu_accounts VALUES(201,101,'active'),(204,101,'active');
                INSERT INTO sem_phase1a_account_grants VALUES(1,101,201,10,NULL),(2,101,201,NULL,NULL);
            """)
        adapter = LocalGrantPrincipalAdapter(auth_path)
        advisor = adapter.resolve(SessionIdentity(1, 'advisor', 101, 10))
        customer = adapter.resolve(SessionIdentity(2, 'customer', 101))
        auth = {'synthetic': True, 'advisor_accounts': sorted(advisor.writable_accounts),
                'customer_readable': sorted(customer.readable_accounts),
                'customer_writable': sorted(customer.writable_accounts), 'ungranted_active_account_excluded':
                (101,204) not in advisor.readable_accounts | customer.readable_accounts}
        with closing(sqlite3.connect(auth_path)) as db, db:
            db.execute("UPDATE users SET role='customer' WHERE id=1")
        try:
            adapter.resolve(SessionIdentity(1, 'advisor', 101, 10))
            raise AssertionError('role mismatch accepted')
        except ScopeDenied:
            auth['db_session_role_mismatch_denied'] = True
        submissions = SubmissionStore(root / 'submissions.sqlite')
        payload = LandingSubmission.model_validate(json.loads((FIXTURES / 'submission.internal.json').read_text(encoding='utf-8')))
        submissions.submit(advisor, payload, [])
        service = ShadowService(submissions)
        view = service.create(advisor, CreateRequest(tenant_id=101,account_id=201,page_id='synthetic-page',submission_revision=1))
        pid = view['plan_id']
        view = service.rule(advisor,pid,RulingRequest(expected_version=1,reason='合成演练裁定'))
        view = service.approve(advisor,pid,ApprovalRequest(expected_version=2,reason='合成演练复核',row_ids=[r['row_id'] for r in view['rows']]))
        workbook = service.export(advisor,pid,'customer')
        (output / 'slice3-review.internal.xlsx').write_bytes(workbook)
        review = service.read(customer,pid)
        data = service.export(advisor,pid,'advisor')
        preview = service.preview(advisor,pid,data,'advisor')
        service.apply(advisor,pid,ApplyRequest(expected_version=2,preview_id=preview['preview_id']))
        restarted = ShadowService(submissions)
        try:
            restarted.apply(advisor,pid,ApplyRequest(expected_version=2,preview_id=preview['preview_id']))
            raise AssertionError('replay accepted')
        except RevisionConflict:
            replay = 'VERSION_CONFLICT'
        evidence = {'synthetic':True,'restart_version':restarted.read(customer,pid)['version'],
                    'replay_code':replay,'executable':False,'go_live_allowed':False,
                    'production_router_mounted':False,'production_database_connected':False}
        for name, value in [('slice3-auth.internal.json',auth),('slice3-review.internal.json',review),
                            ('slice3-persistence.internal.json',evidence)]:
            (output / name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return ['slice3-auth.internal.json','slice3-review.internal.json','slice3-persistence.internal.json','slice3-review.internal.xlsx']

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True)
    print('\n'.join(run(parser.parse_args().output)))

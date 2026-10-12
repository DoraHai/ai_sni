"""Run real Linux GEO scheduler tests without a database, network or provider call.

Use a source-only checkout/snapshot, never a production service directory.
This is a local code/kernel test, not evidence of deployed worker-fleet health.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import socket
import sys
import xml.etree.ElementTree as ET


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geo-root',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--extra-test',type=Path)
    args=parser.parse_args()
    if sys.platform!='linux':
        parser.error('native Linux required; Windows is not a passing substitute')
    root=args.geo_root.resolve()
    os.environ.update(DATABASE_URL='postgresql+asyncpg://offline:offline@127.0.0.1:9/offline',
        BAIDU_APP_ID='offline',BAIDU_SECRET_KEY='offline',BAIDU_DEFAULT_USERNAME='offline',
        BAIDU_DEFAULT_UCID='1',BAIDU_SELF_ACCESS_TOKEN='offline',
        BAIDU_SELF_TOKEN_EXPIRES_AT='2030-01-01T00:00:00Z',
        CRYPTO_MASTER_KEY_B64=base64.b64encode(b'o'*32).decode(),
        ADMIN_API_KEY='offline',APP_ENV='test',PYTHONPATH=str(root))
    # Fail immediately if any supposedly isolated callback attempts I/O.
    def denied(*a,**k):raise RuntimeError('Linux scheduler qualification prohibits network I/O')
    socket.socket.connect=denied
    socket.create_connection=denied
    sys.path.insert(0,str(root));os.chdir(root)
    import pytest
    tests=['tests/test_geo_followup_scheduler.py','tests/test_geo_scheduler.py',
           'tests/test_geo_scheduler_observability.py','tests/test_geo_scheduler_eligibility.py']
    if args.extra_test:tests.append(str(args.extra_test.resolve()))
    evidence=args.report.resolve().with_suffix('.xml')
    rc=pytest.main(['-q','--tb=short','-x','--junitxml='+str(evidence),*tests])
    counts={key:0 for key in ['tests','failures','errors','skipped']}
    if evidence.exists():
        for suite in ET.parse(evidence).getroot().iter('testsuite'):
            for key in counts:counts[key]+=int(suite.attrib.get(key,0))
    files=[root/'app/geo/scheduler.py',root/'app/geo/scheduler_observability.py',
           *[root/test for test in tests if not Path(test).is_absolute()]]
    if args.extra_test:files.append(args.extra_test.resolve())
    report={'schema':1,'captured_at':datetime.now(timezone.utc).isoformat(),
        'platform':platform.system(),'kernel':platform.release(),'machine':platform.machine(),
        'python':platform.python_version(),'test_exit_code':rc,'counts':counts,
        'dependencies':{name:version(name) for name in ['pytest','apscheduler','sqlalchemy','fastapi','pydantic','asyncpg']},
        'source_sha256':{str(file.relative_to(root)) if file.is_relative_to(root) else file.name:
            hashlib.sha256(file.read_bytes()).hexdigest() for file in files},
        'network_io_permitted':False,'database_operations':False,'production_approval':False,
        'scope':'Actual GEO scheduler functions and Linux process/file-lock behavior; callbacks and timers isolated.',
        'limitations':['Guest dependencies differ from production pins; not a production environment-parity check.',
            'No deployed worker-fleet, live queue, service-manager or paid-provider validation.']}
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('LINUX_AUTOMATION_RESULT='+json.dumps(report,ensure_ascii=False))
    raise SystemExit(rc if rc else 1 if counts['skipped'] else 0)


if __name__=='__main__':main()

"""Compose frozen native runtime with central distribution code; no copies or DDL."""
import argparse
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

HEADS={'seo':'139cc7f57650afb1e83930149b6fac33cb9f861a','geo':'ba713f06da330362cd0539531e4edd3216a09d78'}
DEPENDENCIES=('app/config.py','app/database.py','app/security/auth.py','app/security/crypto.py','app/api_metering.py','app/api_controls.py','app/api_connection_config.py','app/api_usage_review_basis.py','scripts/api_metering_schema.sql','scripts/api_controls_schema.sql')

def assemble(root,module):
    root=Path(root).resolve();central=Path(__file__).resolve().parents[1]
    def git(*args):return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
    if git('rev-parse','HEAD')!=HEADS[module] or git('status','--porcelain'):raise RuntimeError('Exact clean frozen native runtime required')
    if 'app' in sys.modules:raise RuntimeError('Assemble before importing app')
    sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
    import app
    app.__path__.append(str(central/'app'))
    for name in ('api_metering','api_controls','api_connection_config'):importlib.import_module('app.'+name)
    central_files=('app/distribution_contract.py','app/distribution_control.py','app/distribution_scheduling.py','app/distribution_publication_results.py','app/distribution_publication_verify.py','app/distribution_planning.py','app/distribution_planning_gateway.py','app/distribution_queue.py','app/distribution_execution.py','app/distribution_execution_capabilities.py','app/distribution_capability_contract.py','app/distribution_handoff_receipts.py','app/api/distribution.py','scripts/distribution_queue_worker.py','scripts/distribution_assembled_worker.py','scripts/distribution_execution_schema.sql','scripts/distribution_capability_registration_schema.sql','docs/fixtures/mht-distribution-capabilities-v1.json','docs/fixtures/distribution-capability-registration-v1.json','docs/fixtures/distribution-handoff-receipt-v1.json','docs/fixtures/distribution-handoff-resolution-read-v1.json')
    return {'native_module':module,'native_head':HEADS[module],'central_head':subprocess.check_output(['git','-C',str(central),'rev-parse','HEAD'],text=True).strip(),'central_files':{name:hashlib.sha256((central/name).read_bytes()).hexdigest() for name in central_files},'dependencies':{name:{'sha256':hashlib.sha256((root/name).read_bytes()).hexdigest(),'source_commit':git('log','-1','--format=%H','--',name)} for name in DEPENDENCIES}}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--native-root',type=Path,required=True);parser.add_argument('--module',choices=HEADS,required=True);parser.add_argument('--manifest',type=Path);parser.add_argument('--once',action='store_true');parser.add_argument('--interval',type=int,default=30);args=parser.parse_args()
    if not 5<=args.interval<=3600:parser.error('interval must be 5..3600')
    if any(os.environ.get(k,'').lower()!='true' for k in ('API_CONTROLS_ENABLED','API_METERING_ENABLED')):parser.error('Assembled entry requires API controls and metering enabled')
    manifest=assemble(args.native_root,args.module)
    if args.manifest:args.manifest.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    spec=importlib.util.spec_from_file_location('assembled_distribution_worker',Path(__file__).parent/'distribution_queue_worker.py')
    worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
    asyncio.run(worker.run(args.once,args.interval,args.module))

if __name__=='__main__':main()

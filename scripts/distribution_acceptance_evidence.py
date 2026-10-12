"""Publish only bounded metadata from this owned acceptance environment."""
import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess

from distribution_acceptance_environment import read, write, status
from distribution_acceptance_probe import checked_root


def build(root):
    root=checked_root(root); central=Path(__file__).resolve().parents[1]
    health=status(root)
    assert all(row.get('running') and not row['automaticSubmit'] and not row['publicationVerified'] for row in health.values())
    runtime={module:{key:value[key] for key in ('central_head','native_head','module','port','schema','automaticSubmit',
        'publicationVerified','production','central_files','acceptance_files','dependencies','planner_provider')}
        for module,value in health.items()}
    for module,value in health.items():
        for name,expected in value['central_files'].items():
            assert hashlib.sha256((central/name).read_bytes()).hexdigest()==expected
        for name,expected in value['acceptance_files'].items():
            path=central/'app/static/distribution-acceptance'/name[3:] if name.startswith('ui/') else central/'scripts'/name
            assert hashlib.sha256(path.read_bytes()).hexdigest()==expected
    modules={};artifacts={}
    for module in ('seo','geo'):
        checkpoint=read(root/(module+'-runtime-checkpoint.json'))
        closure=read(root/(module+'-closure-evidence.json'))
        tasks=checkpoint['task_tuples'];assert len(tasks)==1
        assert tasks[0]['status']=='succeeded' and tasks[0]['receiptCode']=='HUMAN_HANDOFF_ACCEPTED' and tasks[0]['revoked']
        assert tasks[0]['publicationGrantId'] is None
        assert checkpoint['native_publications']==checkpoint['central_publication_reservations']==0
        assert closure['project']['state']=='paused' and closure['active'] is False
        assert sum(row['code']=='HUMAN_HANDOFF_ACCEPTED' for row in checkpoint['handoff_ledger'])==1
        assert any(row['action']=='project_pause' for row in checkpoint['scoped_audit'])
        assert any(row['action']=='account_binding_revoked' for row in checkpoint['scoped_audit'])
        source=read(root/(module+'-source-ready.json'))
        assert source['source_revision']==tasks[0]['contentVersion'] and source['content_digest']==tasks[0]['contentDigest']
        meters=checkpoint['simulation_metering'];assert len(meters)==1
        assert meters[0]['model']=='sim-local-distribution-planning' and meters[0]['provider_request_id']=='acceptance-local-planner'
        modules[module]={'source':source,'task':tasks[0],'project':closure['project'],'binding_active':False,
            'native_publications':0,'central_publication_reservations':0,'sim_meter':meters[0],
            'customer_readonly_DOM':True,'advisor_start_pause_DOM':True,'post_restart_task_count':1,
            'closure_http_checks':closure['http_checks'],'audit_actions':sorted({row['action'] for row in checkpoint['scoped_audit']})}
        for suffix in ('source-ready.json','runtime-checkpoint.json','main-task-tuple.json','closure-evidence.json',
                'ui-start-evidence.json','ui-pause-evidence.json','ui-customer-evidence.json'):
            path=root/(module+'-'+suffix);artifacts[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('seo-ui-review-evidence.json','seo-ui-current-read-evidence.json','seo-ui-session-evidence.json',
            'geo-native-flow-evidence.json','geo-native-intake-evidence.json','geo-fresh-copy-api-journal.json',
            'initial-gates.json','health-summary.json','seo-native-schema.json','geo-mht-gui-flow-blocked.json',
            'geo-fresh-quality-private.json','seo-advisor-approved-paused.png'):
        path=root/name
        if path.is_file():artifacts[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    for module in ('seo','geo'):
        for name in (module+'-advisor-running.png',module+'-advisor-paused-final.png',module+'-customer-handoff-readonly.png'):
            path=root/name;artifacts[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    mht_root=Path('D:/微信小工具箱项目/wechat-toolbox-history-acceptance-20261012')
    mht_head='889abf6e7d27f228f9306f22ba607ca2d9c59345'
    assert subprocess.check_output(['git','-C',str(mht_root),'rev-parse','HEAD'],text=True).strip()==mht_head
    manifest_path=mht_root/'docs/fixtures/distribution-history-build-20261012.json'
    mht_build=read(manifest_path)
    assert len(mht_build['artifacts'])==8
    for item in mht_build['artifacts']:
        assert '/' not in item['name'] and '\\' not in item['name']
        assert hashlib.sha256((mht_root/'out/distribution'/item['name']).read_bytes()).hexdigest()==item['sha256']
    mht_proofs={}
    for name,expected in [('seo-mht-gui-flow-proof.json','04357c0fa3e4e5deca3044c8a5f622d17674b825b0d3855d964e42d5271bf55f'),
            ('seo-history-gui-proof.json','07f7f1849b7b3906602820cd87d40198e1c295dbc6792bd108d294e53d4f8057'),
            ('geo-mht-gui-flow-proof.json',None)]:
        path=root/name;sha=hashlib.sha256(path.read_bytes()).hexdigest();proof=read(path)
        assert expected is None or sha==expected
        assert proof['publicationVerified'] is False and proof['hostStoppedAndClosed'] is True
        mht_proofs[name]={'sha256':sha,'hostStoppedAndClosed':True,'publicationVerified':False}
        artifacts[name]=sha
    root_checks={}
    for path in sorted(root.glob('root-*.json')):
        value=read(path)
        rows=value.get('results',[])
        rows=rows if isinstance(rows,list) else []
        root_checks[path.name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'runtime_pins':[{key:row.get(key) for key in ('module','native_head','central_head')} for row in rows if isinstance(row,dict)]}
    report={'recorded_at':datetime.now(timezone.utc).isoformat(),'runtime':runtime,'modules':modules,
        'input_snapshot_sha256':'f75d382a54ec33f0c892cc4c6afcc17b082c130cc1b58236fb4dde48e383f609',
        'private_artifact_sha256':artifacts,'proof_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'MHT':{'SEO_main_source':'a63b3c89d6ab9161805773341e9d1ef86b690ae7','history_and_GEO_source':mht_head,
            'manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest(),'verified_artifacts':mht_build['artifacts'],
            'GUI_proofs':mht_proofs,'attested_history_targeted_tests':62,'history_tests_repeated_here':False},
        'root_independent_checkpoints':root_checks,
        'original_customer_body_or_credentials_included':False,'production_mutations':False,'formal_publish':False,
        'SEM_AI':False,'actual_supplier_AI':False,'GEO_native_Vue_writing_tested':False,
        'approval_actors':'separate named LOCAL synthetic test roles; not real customer consent',
        'retained_negatives':['original SEO published baijiahao variant','original GEO article17/preview2',
            'local non-UTC article18/variant5','older future-sorted task12 article19/variant7',
            'new task13 article20 missing editorial date','task13 article22 noncanonical metadata sentence'],
        'historical_runtime_pins':{'root_12_boundary_checks':'f1dc68d425a91088823a216327dc68b0be3d5c40',
            'SEO_main_chain':'f27cd2dbc82c087bfeac64eebdc4a3e473ebb910','GEO_main_chain':'1171bed7b3b3cdd0216d6a5b01743db5d969b63b'},
        'boundaries':['No platform browser, cookies, submission or public publication.',
            'Actual native authentication/review/source and central queue/dispatch; no per-draft task POST.',
            'Planner explicitly simulated in process through the actual metering gateway, zero paid API.',
            'Dedicated acceptance DOM only; GEO authoring/fact verification used actual native APIs.',
            'Pause and binding revoke followed completed GUI handoffs, not an active-upload crash experiment.']}
    target=central/'docs/DISTRIBUTION_REAL_CUSTOMER_ACCEPTANCE_20261012.json'
    write(target,report);write(root/'current-runtime-evidence.json',report)
    return hashlib.sha256(target.read_bytes()).hexdigest()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);args=p.parse_args()
    print('metadata_report_sha256='+build(args.root))

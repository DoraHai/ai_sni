from datetime import date, timedelta

from app.geo.content.evidence import generation_evidence_readiness, prepare_facts_for_generation


def fact(i, **changes):
    return {'id':i,'title':f'事实 {i}','statement':'真实资料', 'trust_level':'verified',
            'source_name':'产品手册','status':'active',**changes}


def test_editor_readiness_matches_generation_rules_and_names_exclusions():
    facts=[fact(1),fact(2,trust_level='needs_review'),fact(3,source_name=''),
           fact(4,expires_at=(date.today()-timedelta(days=1)).isoformat())]
    original=[dict(f) for f in facts]
    result=generation_evidence_readiness(facts)
    _,gate=prepare_facts_for_generation(facts,min_eligible=3)
    assert result['ok']==gate['ok']==False
    assert result['eligible_count']==1 and result['bound_count']==4
    assert [(r['id'],r['title'],r['labels']) for r in result['excluded']]==[
        (2,'事实 2',['未核验']),(3,'事实 3',['缺来源']),(4,'事实 4',['已过期'])]
    assert '#2' in result['blocking_message'] and '#4' in result['blocking_message']
    assert facts==original


def test_ready_does_not_claim_generation_or_publication_completed():
    result=generation_evidence_readiness([fact(1),fact(2),fact(3)])
    assert result['ok'] is True and result['blocking_message']==''
    assert 'review_status' not in result and 'completion_evidence' not in result


def test_empty_binding_has_explicit_counts_not_unknown_success():
    result=generation_evidence_readiness([])
    assert not result['ok'] and result['eligible_count']==0 and result['bound_count']==0
    assert result['min_eligible']==3 and result['blocking_message']

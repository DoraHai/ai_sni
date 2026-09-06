from app.geo.content.evidence_cite import build_sentence_citations, citation_verdict
from app.geo.content.claim_guard import ungrounded_claims, format_ungrounded


def test_translation_candidates_preserve_qualification_and_do_not_pass_gate():
    statement = 'MAXXDRIVE is not suitable for belt conveyors unless cooling is installed.'
    facts = [{'id': 6, 'statement': statement, 'title': 'MAXXDRIVE', 'source_name': 'Manual'}]
    body = 'MAXXDRIVE 适用于带式输送系统。'
    rows = build_sentence_citations(body, facts)
    assert not citation_verdict(rows)['ok']
    assert rows[0]['review_reason'] == 'cross_language_unverified'
    assert not rows[0]['cited']
    assert rows[0]['evidence_candidates'][0]['source_statement'] == statement
    assert not rows[0]['evidence_candidates'][0]['verified_translation']
    assert '待核验' in format_ungrounded(ungrounded_claims(body, facts))


def test_same_language_unsupported_claim_is_not_translation_review():
    rows = build_sentence_citations('该产品适用于港口重载作业。', [{'id': 1, 'statement': '该产品配备风扇。'}])
    assert rows[0]['review_reason'] == 'unsupported_claim'
    assert rows[0]['needs_fact']
    assert rows[0]['evidence_candidates'] == []


def test_english_claim_with_chinese_source_remains_pending():
    rows = build_sentence_citations('MAXXDRIVE is suitable for belt conveyors.', [{'id': 1, 'statement': 'MAXXDRIVE 仅在配备冷却装置时适用于带式输送机。'}])
    assert rows[0]['review_reason'] == 'cross_language_unverified'
    assert rows[0]['needs_fact'] and not rows[0]['cited']


def test_english_negation_cannot_be_dropped():
    facts = [{'id': 1, 'statement': 'MAXXDRIVE is not suitable for belt conveyors.'}]
    assert ungrounded_claims('MAXXDRIVE is suitable for belt conveyors.', facts)
    assert not ungrounded_claims(facts[0]['statement'], facts)

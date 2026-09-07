import pytest

from app.geo.content.evidence_cite import build_sentence_citations, citation_verdict
from app.geo.content.claim_guard import ungrounded_claims, format_ungrounded
from app.geo.content.cross_language import evidence_candidates


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


def test_candidates_require_and_prefer_specific_stable_anchor():
    facts = [
        {'id': 4, 'statement': 'MAXXDRIVE industrial units support continuous operation.'},
        {'id': 5, 'statement': 'ACME units provide 20,000 Nm output torque.'},
        {'id': 6, 'statement': 'The MAXXDRIVE XT features a heavily ribbed housing.'},
    ]
    rows = evidence_candidates('MAXXDRIVE XT采用强化肋片外壳。', facts)
    assert [row['fact_id'] for row in rows] == [6]
    assert rows[0]['match_basis'] == 'shared_stable_anchor'
    assert rows[0]['matched_anchors'] == ['maxxdrive xt']
    assert evidence_candidates('连续运行会导致内部温度升高。', facts) == []


def test_verified_translation_must_be_linked_to_current_source_statement():
    statement = 'MAXXDRIVE XT features a heavily ribbed housing.'
    record = {
        'status': 'verified',
        'verified_at': '2026-09-07T00:00:00Z',
        'verified_by': 5,
        'source_statement': statement,
        'text': 'MAXXDRIVE XT 采用强化肋片外壳。',
    }
    fact = {'id': 6, 'statement': statement, 'meta': {'verified_translations': [record]}}
    assert not ungrounded_claims(record['text'], [fact])
    rows = build_sentence_citations(record['text'], [fact])
    assert rows[0]['cited'] and rows[0]['support_basis'] == 'exact_statement'

    changed = {**fact, 'statement': statement + ' Updated.'}
    assert ungrounded_claims(record['text'], [changed])


def test_same_number_without_same_entity_is_not_a_citation():
    facts = [{'id': 1, 'statement': 'ACME mention rate is 60%.', 'title': 'Mention rate'}]
    rows = build_sentence_citations('MAXXDRIVE accuracy is 60%.', facts)
    assert not rows[0]['cited']
    assert rows[0]['support_basis'] is None


@pytest.mark.parametrize(
    "sentence",
    [
        "MAXXDRIVE XT ribbed housing improves efficiency.",
        "MAXXDRIVE XT features a ribbed housing and improves efficiency.",
        "MAXXDRIVE XT does not feature a ribbed housing.",
        "MAXXDRIVE XT features a smooth housing.",
        "MAXXDRIVE XT ribbed housing is not included.",
    ],
)
def test_overlap_cannot_cite_added_effect_negation_or_opposite(sentence):
    fact = {"id": 6, "statement": "MAXXDRIVE XT features a ribbed housing."}
    row = build_sentence_citations(sentence, [fact])[0]
    assert not row["cited"]
    assert row["needs_fact"]
    assert row["support_basis"] is None


@pytest.mark.parametrize(
    "sentence",
    [
        "The gearbox uses titanium gears.",
        "This machine is painted blue.",
        "Operators receive a lifetime warranty.",
        "该产品采用钛合金齿轮。",
        "为何钛合金齿轮更耐用？",
        "## 钛合金齿轮更耐用",
    ],
)
def test_unverified_statements_and_presuppositions_fail_closed(sentence):
    fact = {"id": 6, "statement": "MAXXDRIVE XT features a ribbed housing."}
    row = build_sentence_citations(sentence, [fact])[0]
    assert not row["cited"]
    assert row["is_claim"] and row["needs_fact"]
    assert not citation_verdict([row])["ok"]


def test_neutral_transition_and_question_are_narrowly_exempt():
    facts = [{"id": 6, "statement": "MAXXDRIVE XT features a ribbed housing."}]
    rows = build_sentence_citations(
        "下面按已核验事实逐项说明。\n需要关注什么？",
        facts,
    )
    assert rows and all(not row["cited"] and not row["needs_fact"] for row in rows)
    assert citation_verdict(rows)["ok"]


def test_complete_original_and_verified_translation_remain_citable():
    statement = "MAXXDRIVE XT features a ribbed housing."
    fact = {
        "id": 6,
        "statement": statement,
        "meta": {
            "verified_translations": [{
                "status": "verified",
                "verified_at": "2026-09-07T00:00:00Z",
                "verified_by": 5,
                "source_statement": statement,
                "text": "MAXXDRIVE XT 采用强化肋片外壳。",
            }],
        },
    }
    rows = build_sentence_citations(
        "MAXXDRIVE XT features a ribbed housing.\nMAXXDRIVE XT 采用强化肋片外壳。",
        [fact],
    )
    assert len(rows) == 2
    assert all(row["cited"] and not row["needs_fact"] for row in rows)


@pytest.mark.parametrize(
    "sentence",
    [
        "作者：本产品终身保修且采用钛合金齿轮。",
        "*作者：本产品终身保修且采用钛合金齿轮*",
        "如需享受终身保修，请联系我们咨询。",
        "如果钛合金齿轮更加耐用，建议联系我们咨询。",
        "终身保修如何兑现？",
        "钛合金齿轮有哪些优势？",
        "建议优先核对本产品终身保修后再决策。",
        "官网称终身保修。",
        "报告证明无故障。",
        "来源：https://example.com/manual，官网称终身保修。",
        "耐用。",
        "防爆。",
        "无毒。",
        "50kW。",
    ],
)
def test_format_like_adversarial_claims_cannot_bypass_evidence(sentence):
    row = build_sentence_citations(sentence, [
        {"id": 6, "statement": "MAXXDRIVE XT features a ribbed housing."}
    ])[0]
    assert not row["cited"] and row["needs_fact"]

"""Expose original-language evidence for review; never approve translations by similarity."""
import re


def language(value: str) -> str:
    if re.search(r'[\u4e00-\u9fff]', value or ''):
        return 'zh'
    if len(re.findall(r'[A-Za-z]{2,}', value or '')) >= 3:
        return 'latin'
    return 'unknown'


def evidence_candidates(sentence, facts):
    source_language = language(sentence)
    if source_language == 'unknown':
        return []
    # This is a language mismatch list, NOT a semantic entailment result.
    candidates = []
    for fact in facts or []:
        statement = str(fact.get('statement') or '').strip()
        target_language = language(statement)
        if target_language in {'unknown', source_language}:
            continue
        candidates.append({
            'fact_id': fact.get('id'), 'source_statement': statement,
            'source_name': fact.get('source_name'), 'source_url': fact.get('source_url'),
            'source_language': target_language, 'match_basis': 'language_difference_only',
            'verified_translation': False,
        })
    return candidates[:3]

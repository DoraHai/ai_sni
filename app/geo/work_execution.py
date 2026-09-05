"""Frozen, same-question observations attached to a work ticket; not causal attribution."""
from datetime import timezone

from app.geo.content.sample_provenance import sample_provenance
from app.geo.content.source_opportunities import source_url


def utc_naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def freeze_samples(rows):
    result = []
    for row in rows:
        provenance = sample_provenance(row)
        if (provenance['sample_kind'] != 'real'
                or provenance['sampling_method'] != 'unprimed_json_v2'
                or provenance['analysis_status'] != 'completed'
                or row.citation_accuracy == 'inaccurate' or not row.captured_at):
            raise ValueError('对比仅接受判读完成、引用未标记错误的真实 v2 API 样本')
        result.append(dict(id=row.id, engine=row.engine, captured_at=utc_naive(row.captured_at).isoformat() + 'Z',
                           mentions_brand=bool(row.mentions_brand), raw_text=row.raw_text,
                           cited_urls=sorted({url for raw in (row.cited_urls or []) if (url := source_url(raw))})))
    return result


def compare_samples(before, after, min_samples=3):
    engines = sorted({r['engine'] for r in before + after})
    rows = []
    for engine in engines:
        b = [r for r in before if r['engine'] == engine]
        a = [r for r in after if r['engine'] == engine]
        enough = len(b) >= min_samples and len(a) >= min_samples
        br = sum(r['mentions_brand'] for r in b) / len(b) if b else None
        ar = sum(r['mentions_brand'] for r in a) / len(a) if a else None
        rows.append(dict(engine=engine, before_count=len(b), after_count=len(a), before_rate=br,
                         after_rate=ar, delta=round(ar-br, 4) if enough else None, sufficient=enough))
    comparable = bool(rows) and all(r['sufficient'] for r in rows)
    return dict(engines=rows, comparable=comparable, min_samples_per_engine=min_samples,
                delta=round(sum(r['delta'] for r in rows)/len(rows), 4) if comparable else None,
                note='同题、同引擎分别对比；每个引擎前后至少 3 条。总体差值按引擎等权汇总。仅为所选样本的观察变化，不证明内容修改造成效果。')

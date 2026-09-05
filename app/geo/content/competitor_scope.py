"""Read-only competitor aggregation terminology; does not rewrite stored snapshots."""

def competitor_names(raw):
    return sorted({str(name or '').strip().casefold() for name in (raw or []) if str(name or '').strip()})


WORKBENCH_SCOPE = {
    'version': '1.1',
    'population': '当前活动业务、单元及非品牌点名问题的合格真实快照；按当前问题库筛选，历史结果可能随停用变化。',
    'mention_count': '每条回答对同一竞品最多计1次；名称仅合并大小写及首尾空格，不推断品牌别名。',
    'window': '概览和同题对比为全部历史；日序列按上海日期的所选窗口；近7天来源为滚动168小时内出现的去重URL，并非首次新增。',
    'source_attribution': '来源为提及该竞品的回答中出现的链接，未证明每个链接属于该竞品或支持该竞品结论。',
    'comparison': '工作台探索统计；不是驾驶舱完整自然周、原始巡检证据核验后的统一指标。',
}


def engine_heatmap(rows):
    from collections import Counter
    totals = Counter(r.engine for r in rows)
    own = Counter(r.engine for r in rows if r.mentions_brand)
    competitors = {}
    for row in rows:
        for name in competitor_names(row.competitors):
            competitors.setdefault(name, Counter())[row.engine] += 1
    engines = sorted(totals)
    ranked = sorted(competitors, key=lambda n: (-sum(competitors[n].values()), n))[:5]
    entries = [('本品牌', True, own)] + [(n, False, competitors[n]) for n in ranked]
    return {'engines': engines, 'sample_counts': dict(totals), 'rows': [
        {'name': name, 'own': own_row, 'cells': [counts[e] / totals[e] if totals[e] >= 8 else None for e in engines]}
        for name, own_row, counts in entries],
        'definition': '同一活动问题集合的合格回答，按引擎计算提及回答数/回答总数；每引擎不足8条显示未知；非推荐排名。'}

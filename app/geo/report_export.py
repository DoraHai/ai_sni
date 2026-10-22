"""Build real XLSX and HTML from the same scoped GEO evidence snapshot."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from html import escape
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.geo.content.report_data import citation_rows, local_time, provenance, trend_rows

SECTION_DEFAULTS = [
    {"key": "overview", "title": "概览指标", "visible": True},
    {"key": "trends", "title": "各 AI 引擎提及率与趋势", "visible": True},
    {"key": "citations", "title": "发布 URL 引用", "visible": True},
    {"key": "publications", "title": "发布清单", "visible": True},
    {"key": "provenance", "title": "样本来源与口径", "visible": True},
    {"key": "appendix", "title": "问题与引擎明细", "visible": True},
]
SOURCE_NAMES = {"real": "真实引擎采样", "manual": "人工录入", "simulated": "模拟/演示", "unknown": "来源未知"}

PROJECT_METRICS = (
    ('brand_mention_rate', '品牌提及率', '%'),
    ('brand_mention_answer_count', '品牌提及回答数', ''),
    ('average_recommendation_position', '平均推荐位置（首选=1、备选=2、顺带=3）', ''),
    ('brand_positive_rate', '品牌正向评价率', '%'),
)
PROJECT_STATUS = {'observed': '已检测', 'no_publications': '暂无发布文章',
                  'not_tested': '未检测', 'insufficient_evidence': '引用证据不足',
                  'ready': '充足', 'insufficient': '样本不足'}


def project_period_label(period):
    start, end = (datetime.fromisoformat(period[key].replace('Z', '+00:00'))
                  .astimezone(ZoneInfo('Asia/Shanghai')).date() for key in ('start', 'end'))
    return f'{start} 至 {end - timedelta(days=1)}'


def project_report_sections(data):
    """Shared rows keep PDF and Excel on the exact same read-only projection."""
    summary = data['summary']
    sections = [('四项汇总', ['平台', '指标', '值', '单位'], [
        [label, title, metrics[key], unit]
        for label, metrics in [('总体', summary['metrics'])] + [(r['label'], r['metrics']) for r in summary['by_engine']]
        for key, title, unit in PROJECT_METRICS])]
    sections.append(('标注依据', ['平台', '合格回答', '提及回答', '有效位置数', '首选', '备选', '顺带', '已标注情感数'], [
        [label, m['sample_count'], m['mention_count'], m['valid_position_count'],
         m['position_distribution']['first'], m['position_distribution']['alternative'],
         m['position_distribution']['mentioned'], m['annotated_mention_count']]
        for label, m in [('总体', summary['metrics'])] + [(r['label'], r['metrics']) for r in summary['by_engine']]]))
    sections.append(('问题矩阵', ['问题ID', '业务', '关键词', '问题', '平台', '提及X', '合格Y', '百分比', '状态', '样本时间'], [
        [q['id'], q['business']['name'], q['unit']['display_name'], q['question'], c['label'],
         c['mentioned'], c['total'], c['percentage'], {'small_sample': '小样本', 'observed': '已检测',
         'not_tested': '未检测', 'not_configured': '未配置', 'failed': '失败',
         'tested_excluded': '已检测，未计入'}.get(c['status'], '暂无'), c['last_sample_at']]
        for q in data['questions'] for c in q['by_engine']]))
    coverage = data['citations']['coverage']
    sections.append(('文章覆盖', ['被引H', '已发布U', '百分比', '状态'], [[coverage['cited_articles'],
        coverage['published_articles'], coverage['percentage'], PROJECT_STATUS[coverage['status']]]]))
    sections.append(('文章引用', ['发布ID', '任务ID', '文章ID', '标题', 'URL', '发布时间', '引用x', '合格y', '百分比', '状态'], [
        [a['id'], a['task_id'], a['article_id'], a['title'], a['url'], a['published_at'],
         a['mentioned'], a['total'], a['percentage'], PROJECT_STATUS[a['status']]] for a in data['citations']['items']]))
    sections.append(('引用依据', ['发布ID', '回答ID', '问题ID', '平台key', '回答时间', '证据路径'], [
        [a['id'], e['answer_id'], e['question_id'], e['engine_key'], e['captured_at'], e['answer_path']]
        for a in data['citations']['items'] for e in a['evidence']]))
    sections.append(('站内建议', ['任务ID', '标题', '阶段', '下一步', '检查时间', '建议', '说明', '优先级', '状态'], [
        [r['id'], r['title'], r['phase'], r['next_action'], r['checked_at'], item.get('title'),
         item.get('description'), item.get('priority'), item.get('status')]
        for r in data['recommendations'] for item in r['recommendations'] or [{}]]))
    sections.append(('口径与缺数', ['说明'], [[line] for line in [
        '项目：' + str(data['project']['id']) + ' ' + data['project']['name'],
        '统计周期：' + project_period_label(summary['period']) + '（北京时间）',
        '汇总样本状态：' + PROJECT_STATUS[summary['sample_status']],
        '正式汇总至少8条回答、3题、2引擎；问题格少于3条为小样本；暂无表示缺数，不是0。',
        '提及率=M/N×100；正向率=正向/提及且情感已标注回答×100；位置只对提及且有效位置求均值。',
        '结构扫描：无法确认项目归属，未提供。',
        '证据最新时间：' + str(data['basis']['last_data_at'] or '暂无'),
        *summary['footnotes'],
        *[f"排除原因 {r['code']}：{r['count']}" for r in data['basis']['exclusion_counts']],
    ]]))
    return sections


def build_project_xlsx(data):
    sections = project_report_sections(data)
    if sum(len(rows) for _, _, rows in sections) > 250000:
        raise ValueError('导出明细超过25万行，请缩小项目范围')
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, headers, rows in sections:
        ws = workbook.create_sheet(title)
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='245277')
        for row in rows:
            ws.append([safe_cell('暂无' if value is None else value) for value in row])
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        for column in ws.columns:
            ws.column_dimensions[column[0].column_letter].width = min(65, max(14, max(len(str(c.value or '')) for c in column) + 2))
            for cell in column:
                cell.alignment = Alignment(wrap_text=True, vertical='top')
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def build_project_report_html(data):
    html = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>'
            '@page{size:A4}body{font:12px "Microsoft YaHei","Noto Sans CJK SC",sans-serif;color:#172b3a}'
            'table{border-collapse:collapse;width:100%;font-size:10px;table-layout:fixed}'
            'td,th{border:1px solid #ccd8e0;padding:5px;overflow-wrap:anywhere}th{background:#edf3f7}'
            'thead{display:table-header-group}tr{break-inside:avoid}h2{margin-top:22px;break-after:avoid}</style><body><h1>GEO 项目报告</h1>']
    for title, headers, rows in project_report_sections(data):
        if title == '问题矩阵' and len(data['questions']) > 100:
            rows = rows[:600]
            html.append('<p>问题矩阵超过100题，PDF仅展示前100题；完整明细请下载Excel。</p>')
        html.append('<h2>' + escape(title) + '</h2>')
        html.append(_table(headers, [['暂无' if v is None else v for v in row] for row in rows]) if rows else '<p>暂无</p>')
    return ''.join(html) + '</body></html>'


def report_template(profile: dict | None) -> list[dict]:
    raw = (profile or {}).get("geo_report_template")
    if not isinstance(raw, list) or {x.get("key") for x in raw if isinstance(x, dict)} != {x["key"] for x in SECTION_DEFAULTS}:
        return [dict(x) for x in SECTION_DEFAULTS]
    return [{"key": x["key"], "title": str(x.get("title") or x["key"])[:60], "visible": bool(x.get("visible", True))} for x in raw]


def safe_cell(value):
    if value is None:
        return None
    if isinstance(value, str):
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
    return value


def build_xlsx(data: dict, *, sample_label: str = "") -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    def sheet(name, headers):
        ws = wb.create_sheet(name)
        ws.append([safe_cell(sample_label if sample_label else "GEO 真实记录；空白表示无数据")])
        ws.append(headers)
        for c in ws[2]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="245277")
        ws.freeze_panes = "A3"
        ws.auto_filter.ref = f"A2:{ws.cell(2, len(headers)).column_letter}2"
        return ws
    def format_columns(ws, widths, wrap_columns=()):
        for column, width in enumerate(widths, 1):
            ws.column_dimensions[ws.cell(2, column).column_letter].width = width
        wrapped = Alignment(wrap_text=True, vertical="top")
        for column in wrap_columns:
            for row in ws.iter_rows(min_row=2, min_col=column, max_col=column):
                row[0].alignment = wrapped
    prompts = data["prompts"]
    snaps = data["snapshots"]
    pubs = data["publications"]
    start, end = data["start"], data["end"]
    cites_by_kind = {kind: citation_rows(pubs, snaps, start, end, kind, data.get("publication_checks")) for kind in ("real", "manual", "simulated", "unknown")}
    match_map = {}
    for kind, rows in cites_by_kind.items():
        for pub in rows:
            for match in pub["matches"]:
                match_map.setdefault(match["sample_id"], []).append((match["kind"], pub["published_url"]))
    ws = sheet("样本明细", ["问题ID", "问题", "AI引擎", "日期(北京)", "样本ID", "样本来源", "提及", "引用URL", "精准引用我方URL", "宽松引用我方URL", "回答摘录"])
    engines = sorted({s.engine for s in snaps} | set(data.get("engines") or []))
    by_key = {}
    for s in snaps:
        d = local_time(s.captured_at).date()
        if start <= d <= end:
            by_key.setdefault((s.prompt_id, s.engine, d), []).append(s)
    days = (end - start).days + 1
    if len(prompts) * len(engines) * days + len(snaps) > 250000:
        raise ValueError("导出明细超过 25 万行，请缩短观察期或选择业务范围")
    cursor = start
    while cursor <= end:
        for p in prompts.values():
            for engine in engines:
                for s in by_key.get((p.id, engine, cursor), [None]):
                    matches = match_map.get(s.id, []) if s else []
                    values = [p.id, p.question, engine, cursor, s.id if s else None,
                              SOURCE_NAMES[provenance(s)] if s else "", "是" if s and s.mentions_brand else ("否" if s else ""),
                              "\n".join(s.cited_urls or []) if s else "",
                              "\n".join(u for k, u in matches if k == "exact"),
                              "\n".join(u for k, u in matches if k == "loose"),
                              (s.raw_text or "")[:500] if s else ""]
                    ws.append([safe_cell(v) for v in values])
                    ws.cell(ws.max_row, 4).number_format = "yyyy-mm-dd"
        cursor += timedelta(days=1)
    format_columns(ws, [8, 40, 16, 12, 8, 14, 8, 45, 45, 45, 60], (2, 8, 9, 10, 11))
    for gran, title in (("day", "日提及率"), ("week", "周提及率"), ("month", "月提及率")):
        ws = sheet(title, ["样本来源", "AI引擎", "周期", "提及数", "样本数", "提及率"])
        for kind in ("real", "manual", "simulated", "unknown"):
            for r in trend_rows(snaps, prompts, start, end, gran, kind, data.get("engines")):
                bucket = date.fromisoformat(r["bucket"]) if gran == "day" else r["bucket"]
                ws.append([safe_cell(v) for v in [SOURCE_NAMES[kind], r["engine"], bucket, r["mentions"], r["samples"], r["rate"]]])
                if gran == "day":
                    ws.cell(ws.max_row, 3).number_format = "yyyy-mm-dd"
                ws.cell(ws.max_row, 6).number_format = "0.0%"
        format_columns(ws, [14, 16, 12, 10, 10, 10])
    ws = sheet("URL引用汇总", ["样本来源", "发布ID", "任务ID", "渠道", "发布URL", "精准引用数", "宽松引用数", "命中样本ID"])
    for kind, rows in cites_by_kind.items():
        for r in rows:
            hit_ids = [m["sample_id"] for m in r["matches"]]
            hits = hit_ids[0] if len(hit_ids) == 1 else (",".join(map(str, hit_ids)) if hit_ids else None)
            ws.append([safe_cell(v) for v in [SOURCE_NAMES[kind], r["publication_id"], r["task_id"], r["channel"], r["published_url"], r["exact_count"], r["loose_count"], hits]])
    format_columns(ws, [14, 8, 8, 16, 45, 10, 10, 14], (5,))
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def _table(headers, rows):
    return "<table><thead><tr>" + "".join(f"<th>{escape(str(h))}</th>" for h in headers) + "</tr></thead><tbody>" + "".join(
        "<tr>" + "".join(f"<td>{escape(str(v)) if v is not None else '无数据'}</td>" for v in row) + "</tr>" for row in rows) + "</tbody></table>"


def _daily_line_chart(rows: list[dict], engine: str) -> str:
    """Draw sampled days only; missing days break the line instead of implying zero."""
    left, right, top, bottom = 48, 630, 14, 146
    count = len(rows)
    x_at = lambda i: left + (right - left) * i / max(count - 1, 1)
    y_at = lambda rate: bottom - (bottom - top) * rate
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" class="daily-trend" '
             f'width="650" height="184" viewBox="0 0 650 184" role="img" '
             f'aria-label="{escape(engine, quote=True)} 每日提及率">']
    for rate, label in ((1, "100%"), (.5, "50%"), (0, "0%")):
        y = y_at(rate)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#d7e2e9"/>')
        parts.append(f'<text x="2" y="{y + 4:.1f}" font-size="10">{label}</text>')
    path = []
    for i, row in enumerate(rows):
        if row["rate"] is None:
            continue
        x, y = x_at(i), y_at(row["rate"])
        path.append(f'{"M" if i == 0 or rows[i - 1]["rate"] is None else "L"}{x:.1f},{y:.1f}')
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.8" fill="#2875a9"/>')
    if path:
        parts.append(f'<path d="{" ".join(path)}" fill="none" stroke="#2875a9" stroke-width="2"/>')
    if rows:
        for i in sorted({0, (count - 1) // 2, count - 1}):
            parts.append(f'<text x="{x_at(i):.1f}" y="174" text-anchor="middle" font-size="10">{escape(rows[i]["bucket"])}</text>')
    parts.append('</svg>')
    return "".join(parts)


def _engine_trends(snaps, prompts, start: date, end: date, engines) -> str:
    daily = trend_rows(snaps, prompts, start, end, "day", engines=engines)
    weekly = trend_rows(snaps, prompts, start, end, "week", engines=engines)
    monthly = trend_rows(snaps, prompts, start, end, "month", engines=engines)
    names = sorted({r["engine"] for r in daily})
    blocks = []
    for engine in names:
        engine_daily = [r for r in daily if r["engine"] == engine]
        buckets = [("周", r) for r in weekly if r["engine"] == engine]
        buckets += [("月", r) for r in monthly if r["engine"] == engine]
        rows = [(kind, r["bucket"], r["mentions"], r["samples"],
                 f'{r["rate"]:.1%}' if r["rate"] is not None else "无数据") for kind, r in buckets]
        blocks.append(f'<div class="engine-trend"><h3>{escape(engine)}</h3>'
                      + _daily_line_chart(engine_daily, engine)
                      + _table(["粒度", "周期", "提及数", "样本数", "提及率"], rows) + '</div>')
    return "<p>主趋势：真实引擎采样。日维度明细见 Excel 导出。</p>" + "".join(blocks)


def build_report_html(data: dict, *, template: list[dict] | None = None, sample_label: str = "") -> str:
    start, end = data["start"], data["end"]
    prompts, snaps, pubs = data["prompts"], data["snapshots"], data["publications"]
    real = [s for s in snaps if provenance(s) == "real" and not getattr(prompts.get(s.prompt_id), "is_brand_probe", False)]
    manual = sum(provenance(s) == "manual" for s in snaps)
    simulated = sum(provenance(s) == "simulated" for s in snaps)
    unknown = sum(provenance(s) == "unknown" for s in snaps)
    mentioned = sum(bool(s.mentions_brand) for s in real)
    rate = f"{mentioned / len(real):.1%}" if real else "无数据"
    citations = citation_rows(pubs, snaps, start, end, publication_checks=data.get("publication_checks"))
    matrix = []
    for prompt in prompts.values():
        for engine in sorted({s.engine for s in snaps} | set(data.get("engines") or [])):
            matching = [s for s in real if s.prompt_id == prompt.id and s.engine == engine]
            hits = sum(bool(s.mentions_brand) for s in matching)
            matrix.append((prompt.question, engine, hits, len(matching), f"{hits / len(matching):.1%}" if matching else "无数据"))
    blocks = {
        "overview": f"<p>真实样本 {len(real)} · 提及 {mentioned} · 提及率 {rate} · 问题 {len(prompts)} · 发布链接 {len(pubs)}</p>",
        "trends": _engine_trends(snaps, prompts, start, end, data.get("engines")),
        "citations": "<p>URL匹配表示回答中出现链接；来源页核验表示登记正文与实际页面匹配，不证明AI引用内容准确。核验时间可能晚于观察期。</p>" + _table(["发布 URL", "精准匹配", "宽松匹配", "命中样本", "来源页正文核验"], [(r["published_url"], r["exact_count"], r["loose_count"], ", ".join(str(m["sample_id"]) for m in r["matches"]) or "无数据", "已核验" if r["source_verification"]["verified"] else "待核验") for r in citations]),
        "publications": _table(["渠道", "发布 URL", "发布时刻（北京）"], [(p.channel, p.published_url, local_time(p.published_at).strftime("%Y-%m-%d %H:%M") if p.published_at else "无数据") for p in pubs]),
        "provenance": f"<p>主指标仅统计真实引擎采样。人工录入 {manual} 条、模拟/演示 {simulated} 条、来源未知 {unknown} 条分别保留，不并入主指标。无样本显示无数据。</p>",
        "appendix": _table(["问题", "引擎", "提及数", "样本数", "提及率"], matrix[:100]) + ("<p>问题 × 引擎矩阵仅显示前 100 行；完整记录见 Excel。</p>" if len(matrix) > 100 else ""),
    }
    sections = "".join(f"<section><h2>{escape(item['title'])}</h2>{blocks[item['key']]}</section>" for item in (template or SECTION_DEFAULTS) if item["visible"])
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>
      body {{ font-family: "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", "WenQuanYi Micro Hei", "Microsoft YaHei", "PingFang SC", sans-serif; color:#19344a; font-size:11px; }}
      h1 {{ font-size:26px; }} h2 {{ font-size:16px; border-bottom:2px solid #2875a9; padding-bottom:5px; }}
      section {{ margin-top:20px; }} .engine-trend {{ break-inside:avoid; margin:14px 0; }} h3 {{ font-size:13px; margin:10px 0 3px; }} table {{ border-collapse:collapse; width:100%; table-layout:fixed; }} th,td {{ border:1px solid #cad6de; padding:5px; overflow-wrap:anywhere; }} th {{ background:#e8f2f7; }} svg {{ max-width:100%; }}
    </style></head><body><h1>{escape(sample_label + ' ' if sample_label else '')}GEO 优化报告</h1>
    <p>客户：{escape(str(data.get('client_name') or data['project_name']))} · 项目/业务：{escape(str(data['project_name']))}</p><p>观察期：{start.isoformat()} 至 {end.isoformat()}（北京时间）</p>
    <p>生成时间：{datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')} 北京时间</p>{sections}</body></html>'''

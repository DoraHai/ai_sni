"""Pure monthly-report layout and an isolated Chromium PDF renderer."""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from html import escape
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.seo_page_capture import _BROWSER_CHANNELS
from app.seo_publication_export import (BEIJING, beijing_text,
    effective_publication_template, publication_summary)

DEFAULT_REPORT_SECTIONS = (
    {"key": "cover", "enabled": True, "title": "封面"},
    {"key": "traffic", "enabled": True, "title": "本月流量"},
    {"key": "publication_summary", "enabled": True, "title": "发布汇总"},
    {"key": "publication_detail", "enabled": True, "title": "发布明细"},
    {"key": "screenshot_appendix", "enabled": True, "title": "截图附录"},
)
MAX_APPENDIX_IMAGES = 200
_PDF_SEMAPHORE = asyncio.Semaphore(2)


def validate_report_sections(sections):
    if not isinstance(sections, list) or len(sections) != len(DEFAULT_REPORT_SECTIONS):
        raise ValueError("月报章节须包含全部五个章节")
    allowed = {item["key"] for item in DEFAULT_REPORT_SECTIONS}
    keys = [item.get("key") if isinstance(item, dict) else None for item in sections]
    if set(keys) != allowed or len(set(keys)) != len(keys):
        raise ValueError("月报章节无效或重复")
    result = []
    for item in sections:
        title = item.get("title")
        if not isinstance(item.get("enabled"), bool) or not isinstance(title, str) or not 1 <= len(title.strip()) <= 40:
            raise ValueError("章节显示状态或标题无效")
        result.append({"key": item["key"], "enabled": item["enabled"], "title": title.strip()})
    if not any(item["enabled"] for item in result):
        raise ValueError("至少显示一个章节")
    return result


def _value(value):
    return "无数据" if value is None else str(value)


def _traffic(source, row, configured):
    name = "百度统计" if source == "baidu_tongji" else "GA4"
    if row is None:
        return {"name": name, "uv": "无数据", "pv": "无数据",
                "status": "未拉取" if configured else "未配置", "fetched_at": "无数据", "note": ""}
    status = {"ok": "成功", "no_data": "无数据"}.get(row.status)
    if status is None:
        status = "失败：" + (row.error_message or row.error_code or "未知原因")
    notes = []
    if (row.raw_meta or {}).get("partial"):
        notes.append("本月数据尚未结束，仅包含已拉取日期")
    if row.last_error_code or row.last_error_message:
        notes.append("最近一次拉取失败" + ("：" + row.last_error_message if row.last_error_message else ""))
    elif row.status == "failed" and (row.uv is not None or row.pv is not None):
        notes.append("最近一次拉取失败")
    return {"name": name, "uv": _value(row.uv), "pv": _value(row.pv),
            "status": status, "fetched_at": beijing_text(row.fetched_at) or "无数据",
            "note": "；".join(notes)}


def build_report_context(*, site_name, month, rows, monthly_rows=(), sources=(),
                         columns=None, tenant_name=None, generated_at=None, images=None,
                         sample_label=None):
    """Build display data only from supplied stored rows; no I/O or inferred metrics."""
    generated_at = generated_at or datetime.now(timezone.utc)
    by_source = {row.source: row for row in monthly_rows}
    configured = {row.source for row in sources}
    return {"site": site_name, "tenant": tenant_name, "month": month,
            "month_label": f"{month[:4]}年{int(month[5:])}月",
            "generated_at": beijing_text(generated_at) + " 北京时间",
            "traffic": [_traffic(source, by_source.get(source), source in configured)
                        for source in ("baidu_tongji", "ga4")],
            "rows": list(rows), "summary": publication_summary(rows, site_name, month, generated_at),
            "columns": effective_publication_template(columns), "images": images or {},
            "sample_label": sample_label}


def _e(value):
    return escape(_value(value), quote=True)


def _image_data(data):
    with Image.open(BytesIO(data)) as original:
        if original.width * original.height > 16_000_000:
            raise ValueError("截图图片过大")
        image = original.convert("RGB")
        image.thumbnail((1000, 1600))
        output = BytesIO()
        image.save(output, "JPEG", quality=80, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def render_report_html(context, sections=None):
    sections = validate_report_sections(list(sections or DEFAULT_REPORT_SECTIONS))
    rows, summary = context["rows"], context["summary"]
    body = []
    if context.get("sample_label"):
        body.append(f'<div class="watermark">{_e(context["sample_label"])}</div>')
    for section in sections:
        if not section["enabled"]:
            continue
        key = section["key"]
        body.append(f'<section class="section {key}">')
        if key != "cover":
            body.append(f'<h2>{_e(section["title"])}</h2>')
        if key == "cover":
            body.append('<div class="cover-content">')
            if context.get("tenant"):
                body.append(f'<p>客户：{_e(context["tenant"])}</p>')
            body.append(f'<h1>{_e(context["site"])}</h1><p>{_e(context["month_label"])} SEO 月报</p>'
                        f'<p>生成时间：{_e(context["generated_at"])}</p></div>')
        elif key == "traffic":
            body.append('<table><thead><tr><th>数据源</th><th>UV</th><th>PV</th><th>状态</th><th>拉取时间（北京时间）</th><th>备注</th></tr></thead><tbody>')
            for row in context["traffic"]:
                body.append('<tr>' + ''.join(
                    f'<td class="datetime">{_e(row[field])}</td>' if field == "fetched_at" else f'<td>{_e(row[field])}</td>'
                    for field in ("name", "uv", "pv", "status", "fetched_at", "note")) + '</tr>')
            body.append('</tbody></table>')
        elif key == "publication_summary":
            covered = summary["auto"] + summary["manual"]
            body.append(f'<p>发布总数：{summary["total"]}　截图覆盖：{covered} / {summary["total"]}　'
                        f'自动截图：{summary["auto"]}　人工上传：{summary["manual"]}　'
                        f'截图失败：{summary["failed"]}　无截图：{summary["none"]}</p>')
            body.append('<table><thead><tr><th>平台 / 渠道</th><th>发布数</th></tr></thead><tbody>')
            for platform, count in sorted(summary["platforms"].items()):
                body.append(f'<tr><td>{_e(platform)}</td><td>{count}</td></tr>')
            body.append('</tbody></table>')
        elif key == "publication_detail":
            columns = [col for col in context["columns"] if col["key"] != "image_key"]
            width_weights = {"number": 3.5, "platform": 8, "title": 17, "keywords": 11,
                             "page_url": 21, "published_at": 10, "capture_status": 10,
                             "captured_at": 10, "notes": 9.5}
            total_width = sum(width_weights[col["key"]] for col in columns)
            colgroup = ''.join(
                f'<col style="width:{width_weights[col["key"]] / total_width * 100:.2f}%">'
                for col in columns)
            body.append('<table><colgroup>' + colgroup + '</colgroup><thead><tr>'
                        + ''.join(f'<th>{_e(col["title"])}</th>' for col in columns) + '</tr></thead><tbody>')
            for index, row in enumerate(rows, 1):
                cells = []
                for col in columns:
                    field = col["key"]
                    value = index if field == "number" else row.get(field)
                    if field in {"published_at", "captured_at"}:
                        value = beijing_text(value) if value else None
                    cell_class = ' class="datetime"' if field in {"published_at", "captured_at"} else ''
                    cells.append(f'<td{cell_class}>{_e(value)}</td>')
                body.append('<tr>' + ''.join(cells) + '</tr>')
            body.append('</tbody></table>')
        elif key == "screenshot_appendix":
            image_count = 0
            missing = []
            for row in rows:
                key = row.get("image_key")
                if key and image_count >= MAX_APPENDIX_IMAGES:
                    image_count += 1
                    continue
                data = context["images"].get(key) if key else None
                if data:
                    try:
                        src = _image_data(data)
                    except (OSError, ValueError):
                        data = None
                if data:
                    image_count += 1
                    label = "人工上传" if row.get("capture_kind") == "manual" else "自动截图"
                    body.append(f'<article class="shot"><h3>{_e(row.get("title"))}</h3>'
                                f'<p>{label} · {_e(beijing_text(row.get("captured_at")) or None)}</p>'
                                f'<p class="url">{_e(row.get("page_url"))}</p>'
                                f'<p>{_e(row.get("notes"))}</p><img src="{src}"></article>')
                else:
                    missing.append({**row, "capture_status":
                        "失败：截图图片不可用" if key and image_count < MAX_APPENDIX_IMAGES else row.get("capture_status")})
            overflow = max(0, image_count - MAX_APPENDIX_IMAGES)
            if overflow:
                body.append(f'<p>其余 {overflow} 张截图未收录</p>')
            if missing:
                body.append('<h3>未收录截图的记录</h3><ul>')
                for row in missing:
                    body.append(f'<li>{_e(row.get("title"))} · {_e(row.get("capture_status") or "无截图")}</li>')
                body.append('</ul>')
        body.append('</section>')
    style = """@page{size:A4;margin:18mm 14mm 18mm}@page detail{size:A4 landscape;margin:18mm 14mm 18mm}body{font-family:'Noto Sans CJK SC','Noto Sans SC','Source Han Sans SC','WenQuanYi Micro Hei','Microsoft YaHei','PingFang SC',sans-serif;color:#203247;font-size:10pt}h1{font-size:26pt}h2{font-size:17pt;color:#194c75;border-bottom:2px solid #194c75;padding-bottom:7px}h3{font-size:12pt}.section{break-before:page}.section:first-of-type{break-before:auto}.publication_detail{page:detail}.cover{min-height:240mm}.cover-content{padding-top:70mm;text-align:center}table{border-collapse:collapse;width:100%;table-layout:fixed}thead{display:table-header-group}th,td{border:1px solid #cbd7e1;padding:6px;vertical-align:top;overflow-wrap:anywhere;word-break:break-all}th{background:#eaf1f7}.datetime{white-space:nowrap;word-break:normal;overflow-wrap:normal}.publication_detail table{font-size:10px}.publication_detail th,.publication_detail td{padding:4px}.shot{break-inside:avoid;margin:14px 0 24px;padding-bottom:10px;border-bottom:1px solid #ddd}.shot img{max-width:100%;max-height:210mm;object-fit:contain}.url{word-break:break-all;color:#52677c}.watermark{position:fixed;top:0;right:0;background:#b42318;color:#fff;padding:5px 14px;z-index:10}li{margin:5px 0}"""
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>' + style + '</style></head><body>' + ''.join(body) + '</body></html>'


async def render_report_pdf(html, settings, playwright_factory=None, *, sample_label=None):
    """Render only caller supplied self-contained HTML, with all network requests blocked."""
    channel = settings.seo_page_capture_browser_channel
    executable = settings.seo_page_capture_executable_path
    if channel and channel not in _BROWSER_CHANNELS:
        raise ValueError("invalid_browser_channel")
    if executable and not Path(executable).is_file():
        raise FileNotFoundError(executable)
    if playwright_factory is None:
        from playwright.async_api import async_playwright
        playwright_factory = async_playwright
    options = {"headless": True}
    if executable:
        options["executable_path"] = executable
    elif channel:
        options["channel"] = channel
    async def generate():
        async with _PDF_SEMAPHORE:
            async with playwright_factory() as playwright:
                browser = await playwright.chromium.launch(**options)
                try:
                    context = await browser.new_context(java_script_enabled=False, offline=True,
                                                        service_workers="block", accept_downloads=False)
                    try:
                        async def guard(route):
                            if route.request.url.startswith("data:"):
                                await route.continue_()
                            else:
                                await route.abort()
                        await context.route("**/*", guard)
                        page = await context.new_page()
                        await page.set_content(html, wait_until="load", timeout=30000)
                        label = escape(sample_label or "", quote=True)
                        header = f'<div style="font-size:8px;width:100%;text-align:right;padding-right:14mm;color:#b42318">{label}</div>'
                        footer = '<div style="font-size:8px;width:100%;text-align:center;color:#666"><span class="pageNumber"></span> / <span class="totalPages"></span></div>'
                        return await page.pdf(format="A4", prefer_css_page_size=True,
                                              print_background=True, display_header_footer=True,
                                              header_template=header, footer_template=footer)
                    finally:
                        await context.close()
                finally:
                    await browser.close()
    return await asyncio.wait_for(generate(), timeout=max(45, settings.seo_page_capture_timeout_seconds * 3))

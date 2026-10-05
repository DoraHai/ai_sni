"""Isolated, offline Chromium renderer for GEO reports."""

from __future__ import annotations

import asyncio
from html import escape

from fastapi import HTTPException

_LIMIT = asyncio.Semaphore(2)


async def render_report_pdf(html: str, *, sample_label: str = "", playwright_factory=None, settings=None) -> bytes:
    if playwright_factory is None:
        try:
            from playwright.async_api import async_playwright
            playwright_factory = async_playwright
        except ImportError as exc:
            raise HTTPException(503, "GEO 报告 PDF 暂不可用：服务器未安装 Playwright 与 Chromium") from exc
    if settings is None:
        from app.config import get_settings
        settings = get_settings()
    launch_args = {"headless": True, "timeout": 15000}
    if getattr(settings, "geo_report_browser_executable_path", ""):
        launch_args["executable_path"] = settings.geo_report_browser_executable_path
    elif getattr(settings, "geo_report_browser_channel", ""):
        launch_args["channel"] = settings.geo_report_browser_channel
    async with _LIMIT:
        try:
            async with playwright_factory() as pw:
                browser = await pw.chromium.launch(**launch_args)
                try:
                    context = await browser.new_context(java_script_enabled=False, service_workers="block", offline=True)
                    try:
                        page = await context.new_page()
                        await page.route("**/*", lambda route: route.continue_() if route.request.url.startswith("data:") else route.abort())
                        await page.set_content(html, wait_until="load", timeout=15000)
                        footer = f'<div style="font-size:8px;width:100%;text-align:center;color:#667">{escape(sample_label)}　<span class="pageNumber"></span> / <span class="totalPages"></span></div>'
                        return await asyncio.wait_for(page.pdf(format="A4", print_background=True, display_header_footer=True,
                                              header_template="<span></span>", footer_template=footer,
                                              margin={"top": "16mm", "bottom": "18mm", "left": "15mm", "right": "15mm"}), timeout=20)
                    finally:
                        await context.close()
                finally:
                    await browser.close()
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(503, "GEO 报告 PDF 暂不可用：请安装 Chromium 和中文字体后重试") from exc

"""Fully fabricated AI review draft: python -m scripts.generate_ai_tdk_review_sample OUT_DIR."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace as Row

from app.config import get_settings
from app.seo_monthly_report import render_report_pdf
from app.seo_tdk_review import build_tdk_review_context, render_tdk_review_docx, render_tdk_review_html


def sample_context():
    pages = [
        Row(id=1, url="https://example.invalid/示例数据/首页", title="【示例数据】首页", meta_description="【示例数据】首页说明",
            meta_keywords="【示例数据】关键词", h1="【示例数据】首页", title_suggestion="【示例数据】系统标题",
            description_suggestion="【示例数据】系统描述", target_keyword_id=11, status="proposed"),
        Row(id=2, url="https://example.invalid/示例数据/服务", title="【示例数据】服务页", meta_description="【示例数据】服务说明",
            meta_keywords=None, h1="【示例数据】服务", title_suggestion="【示例数据】系统服务标题",
            description_suggestion=None, target_keyword_id=None, status="proposed"),
        Row(id=3, url="https://example.invalid/示例数据/联系", title="【示例数据】联系页", meta_description=None,
            meta_keywords=None, h1="【示例数据】联系", title_suggestion=None,
            description_suggestion=None, target_keyword_id=None, status="pending"),
        Row(id=4, url="https://example.invalid/示例数据/资料", title="【示例数据】资料页", meta_description=None,
            meta_keywords=None, h1="【示例数据】资料", title_suggestion=None,
            description_suggestion=None, target_keyword_id=None, status="pending"),
    ]
    ai = {
        1: Row(title_status="confirmed", title_final_value="【示例数据】AI 确认标题",
               description_status="modified", description_final_value="【示例数据】人工修改后确认的描述，内容仅为演示用途。" * 3,
               keywords_status="confirmed", keywords_final_value="【示例数据】关键词一、【示例数据】关键词二、【示例数据】关键词三",
               reason="【示例数据】根据已保存页面内容调整措辞。",
               internal_link_suggestions=[{"anchor": "【示例数据】查看资料", "target_page_id": 4,
                   "target_url": pages[3].url, "reason": "【示例数据】相关资料", "status": "confirmed",
                   "final_anchor": "【示例数据】查看资料"}]),
        2: Row(title_status="ai_draft", title_ai_value="【示例数据】未确认草稿", description_status="ai_draft",
               description_ai_value="【示例数据】未确认描述", keywords_status="ai_draft",
               reason="【示例数据】草稿理由", internal_link_suggestions=[]),
        3: Row(title_status="rejected", title_ai_value="【示例数据】已驳回草稿", description_status="rejected",
               description_ai_value="【示例数据】已驳回描述", keywords_status="rejected",
               reason="【示例数据】驳回理由", internal_link_suggestions=[]),
    }
    context = build_tdk_review_context(site_name="【示例数据】演示站点", pages=pages,
        batch_id="【示例数据】批次", generated_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
        keywords=[Row(id=11, keyword="【示例数据】关键词", landing_page=pages[0].url)],
        links=[Row(source_page_id=1, target_page_id=4, anchor_text="【示例数据】已发现链接")],
        ai_suggestions=ai, sample_label="示例数据")
    context["pages"] = context["pages"][:3]
    return context


async def main(directory):
    directory.mkdir(parents=True, exist_ok=True)
    context = sample_context()
    docx = directory / "sample-ai-tdk-review.docx"
    pdf = directory / "sample-ai-tdk-review.pdf"
    docx.write_bytes(render_tdk_review_docx(context))
    pdf.write_bytes(await render_report_pdf(render_tdk_review_html(context), get_settings(), sample_label="示例数据"))
    print(docx, pdf, sep="\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：python -m scripts.generate_ai_tdk_review_sample OUT_DIR")
    asyncio.run(main(Path(sys.argv[1])))

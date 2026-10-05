"""Fully fabricated TDK draft: python -m scripts.generate_tdk_review_sample OUT_DIR."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace as Row

from PIL import Image, ImageDraw, ImageFont

from app.config import get_settings
from app.seo_monthly_report import render_report_pdf
from app.seo_tdk_review import build_tdk_review_context, render_tdk_review_docx, render_tdk_review_html


def screenshot():
    image = Image.new("RGB", (1000, 420), "#e8f0f7")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = ImageFont.truetype(str(font_path), 54) if font_path.is_file() else ImageFont.load_default()
    draw.rectangle((35, 35, 965, 385), outline="#45749b", width=5)
    draw.text((130, 160), "示例截图" if font_path.is_file() else "SAMPLE", font=font, fill="#194c75")
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def sample_context():
    pages = [
        Row(id=1, url="https://example.invalid/sample/1", title="【示例数据】首页", meta_description="【示例数据】产品服务", meta_keywords="示例关键词", h1="示例关键词",
            title_suggestion="【示例数据】示例关键词首页", description_suggestion="【示例数据】示例关键词产品服务", target_keyword_id=11, status="proposed"),
        Row(id=2, url="https://example.invalid/sample/2", title="【示例数据】服务页", meta_description="【示例数据】服务介绍", meta_keywords=None, h1="服务介绍",
            title_suggestion="【示例数据】新版服务页", description_suggestion="【示例数据】新版服务介绍", target_keyword_id=None, status="proposed"),
        Row(id=3, url="https://example.invalid/sample/3", title="【示例数据】联系页", meta_description=None, meta_keywords=None, h1=None,
            title_suggestion=None, description_suggestion=None, target_keyword_id=None, status="pending"),
    ]
    keywords = [Row(id=11, keyword="示例关键词", landing_page=pages[0].url)]
    related_page = Row(id=4, url="https://example.invalid/sample/support", title="【示例数据】资料页",
        meta_description=None, meta_keywords=None, h1=None, title_suggestion=None,
        description_suggestion=None, target_keyword_id=None, status="pending")
    links = [Row(source_page_id=1, target_page_id=4, anchor_text="【示例数据】查看资料")]
    captured_at = datetime(2026, 10, 5, tzinfo=timezone.utc)
    captures = [Row(id=1, relation_id=1, status="succeeded", storage_key="sample.png", captured_at=captured_at)]
    context = build_tdk_review_context(site_name="【示例数据】演示站点", pages=pages + [related_page], batch_id="SAMPLE-001",
        generated_at=captured_at, keywords=keywords, links=links, captures=captures,
        images={"sample.png": screenshot()}, sample_label="示例数据")
    context["pages"] = context["pages"][:3]
    return context


async def main(directory):
    directory.mkdir(parents=True, exist_ok=True)
    context = sample_context()
    docx = directory / "sample-tdk-review.docx"
    pdf = directory / "sample-tdk-review.pdf"
    docx.write_bytes(render_tdk_review_docx(context))
    pdf.write_bytes(await render_report_pdf(render_tdk_review_html(context), get_settings(), sample_label="示例数据"))
    print(f"{docx}: {docx.stat().st_size} bytes")
    print(f"{pdf}: {pdf.stat().st_size} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：python -m scripts.generate_tdk_review_sample OUT_DIR")
    asyncio.run(main(Path(sys.argv[1])))

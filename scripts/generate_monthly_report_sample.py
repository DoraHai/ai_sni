"""Generate a fully fabricated PDF: python -m scripts.generate_monthly_report_sample out.pdf."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

from app.config import get_settings
from app.seo_monthly_report import build_report_context, render_report_html, render_report_pdf


def _placeholder(label: str) -> bytes:
    image = Image.new("RGB", (900, 590), "#e8f0f7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 860, 550), outline="#45749b", width=5)
    font_path = next((path for path in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ) if path.is_file()), None)
    font = ImageFont.truetype(str(font_path), 46) if font_path else ImageFont.load_default()
    draw.text((95, 245), "示例截图" if font_path else "SAMPLE", fill="#194c75", font=font)
    draw.text((95, 320), label, fill="#194c75", font=font)
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def sample_context():
    at = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
    kinds = [("微信公众号", "自动截图", "auto", "auto-1"),
             ("知乎", "人工上传", "manual", "manual-2"),
             ("百家号", "自动截图", "auto", "auto-3"),
             ("搜狐号", "失败：截图超时", "failed", None),
             ("头条号", "无截图", "none", None)]
    rows = []
    images = {}
    for index, (platform, status, kind, key) in enumerate(kinds, 1):
        rows.append({"platform": platform, "title": f"【示例数据】文章标题 {index}",
            "keywords": "【示例数据】关键词", "page_url": f"https://example.invalid/sample/{index}",
            "published_at": at, "capture_status": status, "image_key": key,
            "captured_at": at if key else None, "notes": "【示例数据】仅供版式检查",
            "capture_kind": kind})
        if key:
            images[key] = _placeholder(f"SAMPLE {index}")
    monthly = [SimpleNamespace(source="baidu_tongji", uv=128, pv=306, status="ok",
        fetched_at=at, raw_meta={}, last_error_code=None, last_error_message=None),
        SimpleNamespace(source="ga4", uv=None, pv=None, status="no_data",
        fetched_at=at, raw_meta={}, last_error_code=None, last_error_message=None)]
    return build_report_context(site_name="【示例数据】演示站点", tenant_name="【示例数据】演示客户",
        month="2026-09", rows=rows, monthly_rows=monthly, images=images,
        sample_label="示例数据", generated_at=datetime(2026, 10, 5, tzinfo=timezone.utc))


async def main(path: Path):
    html = render_report_html(sample_context())
    pdf = await render_report_pdf(html, get_settings(), sample_label="示例数据")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf)
    print(f"{path}: {len(pdf)} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：python -m scripts.generate_monthly_report_sample out.pdf")
    asyncio.run(main(Path(sys.argv[1])))

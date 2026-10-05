"""Generate an offline publication list with conspicuously fictional example data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from app.seo_publication_export import build_publication_list_workbook, publication_summary


def example_image() -> bytes:
    image = Image.new("RGB", (800, 1000), "#dce9f2")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((30, 30, 770, 160), fill="#39749a")
    drawing.rectangle((50, 230, 700, 270), fill="#91afc2")
    drawing.rectangle((50, 310, 650, 350), fill="#91afc2")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="离线生成明确标注的示例发布清单")
    parser.add_argument("output", type=Path, help="输出 .xlsx 路径")
    args = parser.parse_args()
    if args.output.suffix.lower() != ".xlsx":
        parser.error("输出路径须以 .xlsx 结尾")
    now = datetime(2026, 9, 18, 2, 30, tzinfo=timezone.utc)
    rows = [
        {"platform": platform, "title": f"【示例数据】{platform}文章", "keywords": "示例关键词",
         "page_url": f"https://example.com/{index}", "published_at": now,
         "capture_status": "自动截图" if index == 1 else "无截图",
         "image_key": "example" if index == 1 else None,
         "captured_at": now if index == 1 else None, "notes": "【示例数据】仅供格式预览",
         "capture_kind": "auto" if index == 1 else "none"}
        for index, platform in enumerate(("知乎", "百家号", "官网"), 1)
    ]
    summary = publication_summary(rows, "【示例数据】演示站点", "2026-09", now)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(build_publication_list_workbook(rows, summary, image_loader=lambda _: example_image()))


if __name__ == "__main__":
    main()

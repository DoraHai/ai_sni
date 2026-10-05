"""Generate a completely synthetic GEO workbook and PDF without a database or AI calls."""

from __future__ import annotations

import asyncio
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.geo.content.attribution import PubRef
from app.geo.report_export import build_report_html, build_xlsx
from app.geo.report_pdf import render_report_pdf


def fake_data():
    tz = ZoneInfo("Asia/Shanghai")
    start = date(2026, 9, 1)
    end = start + timedelta(days=29)
    prompts = {i: SimpleNamespace(id=i, question=f"【示例数据】问题 {i}：产品如何选择？", is_brand_probe=False) for i in range(1, 4)}
    engines = ["【示例数据】引擎甲", "【示例数据】引擎乙", "【示例数据】引擎丙"]
    urls = ["https://sample.example/articles/guide", "https://faq.sample.example/articles/faq", "https://uncited.example.net/articles/uncited"]
    pubs = [PubRef(id=i, published_url=url, channel=f"【示例数据】渠道 {i}", variant_id=i, task_id=i,
                   published_at=datetime(2026, 8, 30, 10, 0)) for i, url in enumerate(urls, 1)]
    snaps = []
    for day in range(30):
        for p in prompts.values():
            engine = engines[(day + p.id) % 3]
            kind = "manual" if day % 11 == 0 else "simulated" if day % 13 == 0 else "real"
            cited = [urls[0] + "?utm_source=demo"] if day % 4 == 0 else ([urls[1] + "/section"] if day % 5 == 0 else [])
            snaps.append(SimpleNamespace(id=len(snaps) + 1, prompt_id=p.id, engine=engine,
                captured_at=datetime(2026, 9, 1 + day, 8, 0, tzinfo=tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
                sample_mode={"real": "openai_compat", "manual": "manual", "simulated": "mock_persona"}[kind],
                patrol_run_id=1 if kind == "real" else None,
                simulated=kind == "simulated", note="", mentions_brand=day % 3 != 0,
                cited_urls=cited, raw_text=f"【示例数据】回答 {day + 1}。"))
    return {"client_name": "【示例数据】客户", "project_name": "【示例数据】项目", "start": start, "end": end,
            "prompts": prompts, "snapshots": snaps, "publications": pubs, "engines": engines}


async def main(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    data = fake_data()
    sample_label = "【示例数据】仅供格式预览"
    (out_dir / "sample-geo-report.xlsx").write_bytes(build_xlsx(data, sample_label=sample_label))
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    settings = SimpleNamespace(geo_report_browser_executable_path=str(chrome) if chrome.exists() else "",
                               geo_report_browser_channel="")
    html = build_report_html(data, sample_label=sample_label)
    pdf = await render_report_pdf(html, sample_label=sample_label, settings=settings)
    (out_dir / "sample-geo-report.pdf").write_bytes(pdf)
    print(f"xlsx={out_dir / 'sample-geo-report.xlsx'}")
    print(f"pdf={out_dir / 'sample-geo-report.pdf'} pages={len(re.findall(rb'/Type\s*/Page\b', pdf))}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".")))

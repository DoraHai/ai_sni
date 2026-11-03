"""P2/P2a：可替换接口，本刀只允许内置本地合成夹具。没有HTTP/OCR SDK。"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

from app.sem_phase0.contracts import LandingSubmission
from app.sem_phase1a.contracts import Source

FIXTURES = Path(__file__).resolve().parents[2] / "docs" / "sem-phase1a" / "fixtures"
FACT_FIELDS = ("product", "benefit", "keywords")
BOUNDARY_FIELDS = ("goal", "budget_cents", "budget_period", "currency", "bid_cap_cents", "regions",
                   "timezone", "schedule", "brand_rules", "negative_keywords", "starts_at", "ends_at")


class CaptureAdapter(Protocol):
    def capture(self, fixture_id: str) -> str: ...


class OcrAdapter(Protocol):
    def recognize(self, fixture_id: str) -> str: ...


class FixtureCapture:
    def capture(self, fixture_id):
        return _read(fixture_id, "html")


class FixtureOcr:
    def recognize(self, fixture_id):
        return _read(fixture_id, "ocr.txt")


def fixture_adapters(backend="fixture") -> tuple[CaptureAdapter, OcrAdapter]:
    if backend != "fixture":
        raise ValueError("本刀只允许fixture；真实HTTP与外部OCR硬关闭")
    return FixtureCapture(), FixtureOcr()


def _read(fixture_id, suffix):
    if fixture_id not in {"launch", "fallback", "empty"}:
        raise ValueError("未知合成夹具")
    return (FIXTURES / f"{fixture_id}.{suffix}").read_text(encoding="utf-8")


class _Fields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}
        self.active = None

    def handle_starttag(self, tag, attrs):
        field = dict(attrs).get("data-field")
        if field in FACT_FIELDS:
            self.active = field
            self.fields[field] = ""

    def handle_data(self, data):
        if self.active:
            self.fields[self.active] += data

    def handle_endtag(self, tag):
        self.active = None


def text_fields(text):
    result = {}
    for line in text.splitlines():
        field, sep, value = line.partition(":")
        if sep and field.strip() in FACT_FIELDS and value.strip():
            result[field.strip()] = value.strip()
    return result


def collect(payload: LandingSubmission, revision: int, submission_hash: str,
            fixture_id: str) -> list[Source]:
    import json

    capture, ocr = fixture_adapters()
    html, ocr_text = capture.capture(fixture_id), ocr.recognize(fixture_id)
    parser = _Fields()
    parser.feed(html)
    sources = []
    for origin, raw, fields in (("fixture_html", html, parser.fields),
                                ("fixture_ocr", ocr_text, text_fields(ocr_text)),
                                ("submission", payload.page_content, text_fields(payload.page_content))):
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        for field, value in fields.items():
            if value.strip():
                sources.append(Source(source_id=f"s-{len(sources)+1}", field=field, value=value,
                                      origin=origin, artifact_sha256=digest,
                                      locator=f"fixture:{fixture_id}/{origin}/{field};page:{payload.landing_page_id};revision:{revision}"))
    data = payload.model_dump(mode="json")
    for field in BOUNDARY_FIELDS:
        sources.append(Source(source_id=f"s-{len(sources)+1}", field=field,
                              value=json.dumps(data[field], ensure_ascii=False), origin="submission",
                              artifact_sha256=submission_hash,
                              locator=f"phase0:{payload.landing_page_id}/revision:{revision}/{field}"))
    if not all(any(s.field == field for s in sources) for field in FACT_FIELDS):
        raise ValueError("合成识别及提交内容缺项，返回P1补内容")
    return sources


def comparisons(sources):
    results = []
    priority = {"fixture_html": 0, "fixture_ocr": 1, "submission": 2}
    for field in sorted({s.field for s in sources}):
        candidates = sorted((s for s in sources if s.field == field),
                            key=lambda s: (priority[s.origin], s.source_id))
        # 识别值优先；HTML和假OCR都有值时，按固定HTML优先展示，顾问仍可改判。
        results.append({"field": field, "default_source_id": candidates[0].source_id,
                        "conflict": len({s.value for s in candidates}) > 1,
                        "candidates": [s.model_dump() for s in candidates]})
    return results

"""Render synthetic SEO read fixtures through the production adapter.

This is an offline example entry point. It performs no HTTP, database, crawl,
generation or publication work and refuses documents not marked synthetic.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.seo_workbench_adapter import (  # noqa: E402
    WorkbenchPayloadError,
    WorkbenchResponseContext,
    adapt_seo_workbench_item,
)


PAGE_MESSAGES = {
    "not_linked": "尚未关联发布页面，页面检查状态未知。",
    "missing_url": "发布记录没有发布地址，暂时无法检查对应页面。",
    "unmapped": "已有发布地址，但尚未关联 SEO 页面记录，暂时无法展示页面检查。",
    "ambiguous": "发布地址对应多个候选页面，需要先确认正确页面。",
    "source_page_only": "当前只有内容任务的来源或承接页，不能当作实际发布页面。",
    "linked_page_unavailable": "已明确关联发布页面，但还没有可用的页面详情。",
    "matched": "已明确关联发布页面；检查结果与发布结果分别展示。",
}


def normalize_attempts_by_publication(
    value: Any,
) -> dict[int, Sequence[Mapping[str, Any]]]:
    """Normalize JSON object keys without silently merging publication IDs."""

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise WorkbenchPayloadError("attempts_by_publication 格式无效")
    result: dict[int, Sequence[Mapping[str, Any]]] = {}
    for key, attempts in value.items():
        if isinstance(key, bool):
            raise WorkbenchPayloadError("publication_id 无效")
        if isinstance(key, int):
            publication_id = key
        elif isinstance(key, str) and key.strip().isdigit():
            publication_id = int(key.strip())
        else:
            raise WorkbenchPayloadError("publication_id 无效")
        if publication_id <= 0:
            raise WorkbenchPayloadError("publication_id 无效")
        if publication_id in result:
            raise WorkbenchPayloadError("publication_id 归一化后重复")
        if not isinstance(attempts, Sequence) or isinstance(attempts, (str, bytes)):
            raise WorkbenchPayloadError("发布尝试列表格式无效")
        result[publication_id] = attempts
    return result


def customer_messages(view: Mapping[str, Any]) -> list[dict[str, str]]:
    """Produce presentation hints without changing adapter states."""

    messages = [
        {"kind": "review", "text": str(view["review"]["label"])},
    ]
    summary = view["publication_summary"]
    if summary["record_count"] == 0:
        publication_text = "尚无分平台发布记录。"
    else:
        publication_text = (
            f"共 {summary['record_count']} 条分平台发布记录："
            f"成功 {summary['successful_count']} 条，失败 {summary['failed_count']} 条。"
        )
    messages.append({"kind": "publication", "text": publication_text})
    mapping_state = str(view["page_evidence"]["mapping_state"])
    messages.append(
        {
            "kind": "page_check",
            "text": PAGE_MESSAGES.get(mapping_state, "页面关联状态未知，暂不展示检查结论。"),
        }
    )
    messages.append(
        {
            "kind": "search_performance",
            "text": "单篇文章点击数据当前不可用，不从业务总点击或关键词关系推算。",
        }
    )
    return messages


def render_document(document: Mapping[str, Any], request_id: str) -> dict[str, Any]:
    """Render all scenarios using only ``raw`` and explicit consumer input."""

    if document.get("synthetic") is not True or document.get("production_data") is not False:
        raise WorkbenchPayloadError("示例入口只接受明确标记的纯合成数据")
    if document.get("executable_urls") is not False:
        raise WorkbenchPayloadError("示例入口拒绝可能执行的 URL")

    items = []
    for scenario in document.get("scenarios") or []:
        raw = scenario.get("raw")
        if not isinstance(raw, Mapping) or not isinstance(raw.get("content"), Mapping):
            raise WorkbenchPayloadError("场景缺少 raw.content")
        content = raw["content"]
        context = WorkbenchResponseContext(
            tenant_id=int(content["tenant_id"]),
            site_id=int(content["site_id"]),
            request_id=f"{request_id}:{scenario['id']}",
        )
        consumer_input = scenario.get("consumer_input") or {}
        if not isinstance(consumer_input, Mapping):
            raise WorkbenchPayloadError("consumer_input 格式无效")
        view = adapt_seo_workbench_item(
            raw,
            expected_context=context,
            response_context=context,
            attempts_by_publication=normalize_attempts_by_publication(
                consumer_input.get("attempts_by_publication")
            ),
            page_candidates=consumer_input.get("page_candidates") or (),
            page_binding=consumer_input.get("page_binding"),
        )
        items.append(
            {
                "scenario_id": scenario["id"],
                "scope": {"tenant_id": context.tenant_id, "site_id": context.site_id},
                "view": view,
                "customer_messages": customer_messages(view),
            }
        )
    return {
        "schema": "seo_workbench_customer_example_v1",
        "synthetic": True,
        "source_schema": document.get("schema"),
        "item_count": len(items),
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the offline SEO workbench example")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--request-id", default="offline-example")
    args = parser.parse_args()
    document = json.loads(args.input.read_text(encoding="utf-8"))
    result = render_document(document, args.request_id)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

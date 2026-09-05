"""Evidence-backed content opportunities, never inferred publisher rankings."""

import hashlib
import json
from urllib.parse import urlsplit, urlunsplit

from app.geo.content.sample_provenance import sample_provenance
from app.geo.content.snapshots import domain_matches


def source_url(value):
    try:
        url = urlsplit(str(value or "").strip())
        if url.scheme.lower() not in {"http", "https"} or not url.hostname or url.username or url.password:
            return None
        # Validate ports and discard fragments; query parameters may identify the article.
        _ = url.port
        return urlunsplit((url.scheme.lower(), url.netloc.lower(), url.path or "/", url.query, ""))
    except ValueError:
        return None


def build_source_opportunities(rows, *, prompts, own_domains):
    rows = list(rows)
    rows_by_id = {row.id: row for row in rows}
    buckets = {}
    excluded = {"non_api": 0, "legacy_method": 0, "needs_review": 0, "brand_probe_or_missing_prompt": 0, "inaccurate_citation": 0}
    eligible = 0
    seen = set()
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        provenance = sample_provenance(row)
        prompt = prompts.get(row.prompt_id)
        if provenance["sample_kind"] != "real":
            excluded["non_api"] += 1
            continue
        if provenance["sampling_method"] != "unprimed_json_v2":
            excluded["legacy_method"] += 1
            continue
        if provenance["analysis_status"] != "completed":
            excluded["needs_review"] += 1
            continue
        if prompt is None or prompt.is_brand_probe:
            excluded["brand_probe_or_missing_prompt"] += 1
            continue
        if getattr(row, "citation_accuracy", None) == "inaccurate":
            excluded["inaccurate_citation"] += 1
            continue
        eligible += 1
        urls = sorted({url for raw in (row.cited_urls or []) if (url := source_url(raw))})
        external = [url for url in urls if not any(
            domain_matches(urlsplit(url).hostname, own) for own in own_domains
        )]
        own_hit = any(any(domain_matches(urlsplit(url).hostname, own) for own in own_domains) for url in urls)
        bucket = buckets.setdefault(row.prompt_id, {
            "prompt_id": row.prompt_id, "question": prompt.question,
            "sample_count": 0, "sample_ids": [], "missing_brand_count": 0,
            "external_citation_count": 0, "own_citation_count": 0,
            "engines": set(), "evidence": [],
        })
        bucket["sample_count"] += 1
        bucket["sample_ids"].append(row.id)
        bucket["own_citation_count"] += int(own_hit)
        if external:
            bucket["external_citation_count"] += 1
            bucket["missing_brand_count"] += int(not row.mentions_brand)
            bucket["engines"].add(row.engine)
            bucket["evidence"].append({
                "snapshot_id": row.id, "engine": row.engine,
                "captured_at": row.captured_at.isoformat() if row.captured_at else None,
                "mentions_brand": bool(row.mentions_brand), "urls": external,
                "citation_accuracy": getattr(row, "citation_accuracy", None) or "unknown",
            })
    items = []
    for bucket in buckets.values():
        if not bucket["external_citation_count"]:
            continue
        # Without owned-domain configuration absence cannot be asserted.
        gap = bucket["missing_brand_count"] > 0
        own_gap = bool(own_domains) and bucket["own_citation_count"] == 0
        if not gap and not own_gap:
            continue
        repeated = bucket["external_citation_count"] >= 3 and len(bucket["engines"]) >= 2
        bucket["priority"] = "优先核对" if repeated else "补充采样"
        bucket["reason"] = (
            f"{bucket['external_citation_count']} 条样本记录{'第三方' if own_domains else '待确认归属的'}引用，其中 {bucket['missing_brand_count']} 条未提及品牌。"
            + ("本组样本未见自有域引用。" if own_gap else "")
        )
        bucket["next_action"] = (
            "先核验来源页面与问题的相关性，整理回答缺少的品牌事实、对比依据与适用条件，再补充内容并用同一问题复测。"
            if gap else "核对自有内容是否完整回答该问题，补充可核验事实与清晰出处，再用同一问题复测。"
        )
        sample_ids = set(bucket["sample_ids"])
        version_rows = [{
            "id": row.id, "engine": row.engine,
            "captured_at": row.captured_at.isoformat() if row.captured_at else None,
            "raw_text": getattr(row, "raw_text", None),
            "mentions_brand": row.mentions_brand, "cited_urls": row.cited_urls,
            "note": getattr(row, "note", None), "sample_mode": row.sample_mode,
            "simulated": row.simulated, "citation_accuracy": getattr(row, "citation_accuracy", None),
        } for row in (rows_by_id[sid] for sid in sorted(sample_ids))]
        version_rows.sort(key=lambda row: row["id"])
        version = {"question": bucket["question"], "own_domains": sorted(own_domains), "samples": version_rows}
        bucket["evidence_version"] = hashlib.sha256(
            json.dumps(version, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        bucket["engines"] = sorted(bucket["engines"])
        bucket["evidence"].sort(key=lambda e: (e["captured_at"] or "", e["snapshot_id"]), reverse=True)
        items.append(bucket)
    items.sort(key=lambda x: (x["priority"] != "优先核对", -x["missing_brand_count"], -x["external_citation_count"], x["prompt_id"]))
    return {
        "items": items, "eligible_samples": eligible, "excluded_samples": excluded,
        "own_domains_configured": bool(own_domains),
        "note": "仅使用判读完成的 v2 API 非品牌点名样本；排序是内部核对顺序，不是效果评分。引用及品牌判读仍需人工核验。",
    }

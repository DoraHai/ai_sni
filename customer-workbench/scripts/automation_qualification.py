"""Offline SEO/GEO proposal qualification. Never calls a provider or writes business data.

Production validators run in a separate process with network connections disabled.
Recorded model output, synthetic fence tests and human business scores stay distinct.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

DIMENSIONS = {"facts": 30, "focus": 20, "actionability": 20,
              "traceability": 15, "human_boundary": 15}
CRITICAL = {"cross_customer", "invented_critical_fact", "approval_bypass"}
THRESHOLD = 85
COMPLETION = re.compile(r"(?:网站|官网|方案|页面|本方案|本页面).{0,12}(?:已经|已)(?:自动)?(?:实施|发布|上线|验收|修改)|(?:已完成|已经完成).{0,8}(?:网站修改|发布|验收)")


def load_json(path: Path):
    raw = path.read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError("qualification input exceeds 2 MB")
    return json.loads(raw.decode("utf-8-sig"))


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_revision(root: Path) -> str:
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                   text=True).strip()


def git_clean(root: Path) -> bool:
    return not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip()


def human_score(review, *, accepted: bool, source_kind: str):
    """A score is an explicit reviewer assessment, never inferred from test counts."""
    pending = {"score": None, "decision": "human_review_pending"}
    if not accepted:
        return {"score": None, "decision": "automatic_gate_rejected"}
    if source_kind == "synthetic_guard_fixture":
        return {"score": None, "decision": "synthetic_fixture_not_model_quality"}
    if review is None:
        return pending
    if set(review) != {"reviewer", "notes", "scores", "critical_findings"}:
        raise ValueError("review must use the fixed rubric")
    if not isinstance(review["reviewer"], str) or not review["reviewer"].strip():
        raise ValueError("reviewer required")
    if not isinstance(review["notes"], str) or len(review["notes"].strip()) < 15:
        raise ValueError("review needs substantive evidence notes")
    scores = review["scores"]
    if not isinstance(scores, dict) or set(scores) != set(DIMENSIONS):
        raise ValueError("all five dimensions required")
    for key, maximum in DIMENSIONS.items():
        if type(scores[key]) is not int or not 0 <= scores[key] <= maximum:
            raise ValueError("invalid dimension score")
    flags = review["critical_findings"]
    if not isinstance(flags, list) or any(flag not in CRITICAL for flag in flags):
        raise ValueError("invalid critical finding")
    score = sum(scores.values())
    return {"score": score, "decision": "critical_rejected" if flags else
            "business_review_passed" if score >= THRESHOLD else "business_review_failed"}


def validate_worker(root: Path, module: str, cases: list):
    # The worker is a local process, not a model execution endpoint.
    environment = dict(os.environ)
    environment.update(DATABASE_URL="postgresql+asyncpg://offline:offline@127.0.0.1:9/offline",
                       APP_ENV="test", ENV="test", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "_validate",
                             "--root", str(root), "--module", module],
                            input=json.dumps(cases, ensure_ascii=False),
                            capture_output=True, encoding="utf-8", env=environment,
                            cwd=root, timeout=45)
    if result.returncode:
        # Do not expose provider bodies, credentials or arbitrary import errors.
        raise RuntimeError("offline production-validator worker failed")
    return json.loads(result.stdout)


def _worker(root: Path, module: str):
    import socket

    def denied(*args, **kwargs):
        raise RuntimeError("offline qualification prohibits network connections")

    socket.socket.connect = denied
    socket.create_connection = denied
    sys.path.insert(0, str(root))
    # No .env, production credentials or inherited provider configuration.
    # Both modules import database helpers, but never establish a connection.
    import base64
    from app.config import Settings
    from app.api_connection_config import current_settings
    current_settings.set(Settings(_env_file=None,
        database_url="postgresql+asyncpg://offline:offline@127.0.0.1:9/offline",
        baidu_app_id="offline", baidu_secret_key="offline", baidu_default_username="offline",
        baidu_default_ucid=1, baidu_self_access_token="offline",
        baidu_self_token_expires_at="2030-01-01T00:00:00Z",
        crypto_master_key_b64=base64.b64encode(b"o" * 32).decode(), admin_api_key="offline"))
    if module == "seo":
        from app.seo_onsite_ai import validate_result
        validate = lambda case: validate_result(case["output"], case["input"])
    else:
        from app.geo.onsite_ai import validate_provider_result
        validate = lambda case: validate_provider_result(case["output"],
            current_items=case["input"]["items"], facts=case["input"]["facts"],
            domain=case["input"]["project"]["domain"])
    cases = json.loads(sys.stdin.read())
    outcomes = []
    for case in cases:
        try:
            items, explanations = validate(case)
        except Exception as exc:
            # Only an expected validation rejection is a successful fence test.
            from fastapi import HTTPException
            from pydantic import ValidationError
            if not isinstance(exc, (ValueError, HTTPException, ValidationError)):
                raise
            outcomes.append({"name": case["name"], "validator_accepted": False,
                             "accepted": False, "reason": "production_validator_rejected"})
            continue
        text = json.dumps(case["output"], ensure_ascii=False)
        claimed_completion = bool(COMPLETION.search(text))
        blank_kinds = set(case.get("must_be_blank_kinds", []))
        blank_ok = all(not item["expected"].strip() for item in items if item["kind"] in blank_kinds)
        outcomes.append({"name": case["name"], "validator_accepted": True,
                         "accepted": not claimed_completion and blank_ok,
                         "reason": "completion_claim_requires_rejection" if claimed_completion else
                                   "missing_evidence_not_blank" if not blank_ok else "accepted",
                         "items": len(items), "nonempty_items": sum(bool(i["expected"].strip()) for i in items)})
    print(json.dumps(outcomes, ensure_ascii=False))


def evaluate(root: Path, module: str, source: Path, reviews: Path | None = None):
    packet = load_json(source)
    if packet.get("schema") != 1 or packet.get("module") != module:
        raise ValueError("wrong qualification envelope")
    source_kind = packet.get("source_kind")
    if source_kind not in {"synthetic_guard_fixture", "recorded_provider_response"}:
        raise ValueError("unknown evidence source")
    cases = packet.get("cases")
    if not isinstance(cases, list) or not cases or len(cases) > 100:
        raise ValueError("1..100 cases required")
    names = [case.get("name") for case in cases]
    if any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", name) for name in names) or len(set(names)) != len(names):
        raise ValueError("case IDs must be safe and unique")
    review_map = load_json(reviews) if reviews else {}
    if not isinstance(review_map, dict) or set(review_map) - set(names):
        raise ValueError("reviews must reference current case IDs")
    start_revision = git_revision(root)
    validator = root / ("app/seo_onsite_ai.py" if module == "seo" else "app/geo/onsite_ai.py")
    validator_hash = fingerprint(validator)
    outcomes = validate_worker(root, module, cases)
    if start_revision != git_revision(root) or validator_hash != fingerprint(validator):
        raise RuntimeError("candidate changed during qualification")
    by_name = {case["name"]: case for case in cases}
    for result in outcomes:
        case = by_name[result["name"]]
        expected = case.get("expected_outcome", "accept")
        if expected not in {"accept", "reject"}:
            raise ValueError("invalid expected outcome")
        result["expectation_met"] = result["accepted"] == (expected == "accept")
        result.update(human_score(review_map.get(result["name"]), accepted=result["accepted"], source_kind=source_kind))
    return {"schema": 1, "module": module, "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "candidate_commit": start_revision, "candidate_tree_clean": git_clean(root), "validator_sha256": validator_hash,
            "input_sha256": fingerprint(source), "source_kind": source_kind,
            "source_provenance": packet.get("provenance", {}), "rubric": DIMENSIONS,
            "business_threshold": THRESHOLD, "cases": outcomes,
            "expectations_passed": sum(item["expectation_met"] for item in outcomes),
            "total": len(outcomes), "model_calls_made": 0,
            "business_scores_available": sum(item["score"] is not None for item in outcomes),
            "production_approval": False,
            "limitations": ["Offline replay does not prove current provider availability.",
                "Synthetic fixtures do not earn model-quality scores.",
                "Business scores require explicit human review; no score is derived from test counts.",
                "Completion-text screening is an evaluation gate, not a new deployed runtime guard."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["evaluate", "_validate"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--module", choices=["seo", "geo"], required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.command == "_validate":
        _worker(args.root.resolve(), args.module)
        return
    if not args.input or not args.report:
        parser.error("evaluate requires --input and --report")
    report = evaluate(args.root.resolve(), args.module, args.input, args.reviews)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ["module", "candidate_commit", "total",
        "expectations_passed", "business_scores_available", "model_calls_made"]}))
    if report["expectations_passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""只用临时SQLite和合成图文；不导入app.main/config/database，不读取.env。"""
import copy
import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
from pydantic import ValidationError

from app.sem_phase0.contracts import LandingSubmission
from app.sem_phase0.router import create_router
from app.sem_phase0.rules import CheckInput, RuleConfig, check_plan
from app.sem_phase0.screenshots import Screenshot, clean_screenshot
from app.sem_phase0.store import AdvisorPrincipal, RevisionConflict, ScopeDenied, SubmissionStore
from app.sem_phase0.templates import export_baidu_execution_file, synthetic_sample, write_internal_sample


def submission(**changes):
    data = dict(tenant_id=101, account_id=201, product_line_id="synthetic-product", landing_page_id="page-a",
                expected_revision=0, case_type="new_product", account_ready=True,
                landing_url="https://example.invalid/a", page_content="合成页面内容，只作内部契约演练。",
                goal="合成询盘目标", budget_cents=12345, budget_period="daily", currency="CNY",
                bid_cap_cents=200, regions=["合成地域"], timezone="Asia/Shanghai",
                schedule=[dict(days=[1, 2, 3, 4, 5], start_hour=9, end_hour=18)],
                brand_rules="不使用他人品牌", negative_keywords=[], starts_at="2026-11-01T09:00:00+08:00",
                ends_at=None, no_deadline_explicit=True, link_source="email", authorized_scope="合成页面内容整理")
    return {**data, **changes}


def principal(role="advisor", accounts=frozenset({(101, 201)}), actor="synthetic-advisor"):
    return AdvisorPrincipal(actor, role, accounts)


@pytest.mark.parametrize("field", ["landing_url", "page_content", "product_line_id", "tenant_id", "account_id",
                                   "goal", "budget_cents", "budget_period", "currency", "bid_cap_cents", "regions",
                                   "schedule", "brand_rules", "starts_at", "no_deadline_explicit", "authorized_scope"])
def test_required_fields_never_default(field):
    data = submission()
    del data[field]
    with pytest.raises(ValidationError):
        LandingSubmission.model_validate(data)


@pytest.mark.parametrize("changes", [
    {"case_type": "page_change"}, {"account_ready": False}, {"budget_cents": 0}, {"budget_cents": True},
    {"budget_cents": "10000"}, {"budget_cents": 1.2}, {"page_content": "   "}, {"regions": [" "]},
    {"no_deadline_explicit": False}, {"case_type": "event"}, {"starts_at": "2026-11-01T09:00:00"},
    {"ends_at": "2026-10-01T09:00:00+08:00", "no_deadline_explicit": False},
    {"ends_at": "2026-12-01T09:00:00+08:00"}, {"submitted_by": "forged"}, {"customer_confirmation": "approved"},
    {"landing_url": "file:///page"}, {"landing_url": "https://user:pass@example.invalid/a"},
    {"landing_url": "http://127.0.0.1/a"}, {"landing_url": "https://example.invalid:bad/a"},
    {"schedule": [{"days": [1], "start_hour": 18, "end_hour": 9}]},
])
def test_invalid_contract_is_blocked(changes):
    with pytest.raises(ValidationError):
        LandingSubmission.model_validate(submission(**changes))


def test_allowed_cases_and_explicit_deadline():
    for case in ("new_account", "new_product", "event"):
        assert LandingSubmission.model_validate(submission(case_type=case, no_deadline_explicit=False,
                                                          ends_at="2026-12-01T09:00:00+08:00")).budget_cents == 12345


def png():
    out = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("author", "synthetic-private-metadata")
    Image.new("RGB", (8, 8), "white").save(out, format="PNG", pnginfo=metadata)
    return out.getvalue()


@pytest.mark.parametrize("extension,fmt,mime", [("png", "PNG", "image/png"), ("jpg", "JPEG", "image/jpeg"),
                                                ("jpeg", "JPEG", "image/jpeg")])
def test_image_decode_and_metadata_cleaning(extension, fmt, mime):
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(out, format=fmt)
    raw = png() if fmt == "PNG" else out.getvalue()
    data, meta = clean_screenshot(Screenshot("page-a", f"demo.{extension}", mime, raw))
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == "PNG" and not image.info and not image.getexif()
    assert meta["ocr_status"] == "not_connected"
    assert "original_sha256" in meta and "clean_sha256" in meta


@pytest.mark.parametrize("name,mime,data", [("demo.pdf", "application/pdf", b"%PDF"),
    ("demo.png", "image/png", b"not a png"),
    ("demo.txt", "text/plain", b"text")])
def test_disguised_or_document_upload_rejected(name, mime, data):
    with pytest.raises(ValueError):
        clean_screenshot(Screenshot("page-a", name, mime, data))


def test_exif_orientation_preserved_when_metadata_removed():
    out = io.BytesIO()
    image = Image.new("RGB", (8, 4), "white")
    exif = image.getexif()
    exif[274] = 6
    image.save(out, format="JPEG", exif=exif)
    data, meta = clean_screenshot(Screenshot("page-a", "rotated.jpg", "image/jpeg", out.getvalue()))
    with Image.open(io.BytesIO(data)) as cleaned:
        assert cleaned.size == (4, 8) and not cleaned.getexif()
    assert (meta["width"], meta["height"]) == (4, 8)


def test_store_versions_ownership_and_restart(tmp_path):
    path = tmp_path / "private.sqlite"
    store = SubmissionStore(path)
    payload = LandingSubmission.model_validate(submission())
    result = store.submit(principal(), payload, [Screenshot("page-a", "shot.png", "image/png", png())])
    assert result["revision"] == 1 and result["submitted_by"] == "synthetic-advisor"
    assert result["customer_confirmation"] == "pending" and not result["execution_export_enabled"]
    store = SubmissionStore(path)
    original = store.read(principal(), 101, 201, "page-a", 1)
    assert original["payload"]["budget_cents"] == 12345 and len(original["screenshots"]) == 1
    assert store.submit(principal(actor="second-advisor"), LandingSubmission.model_validate(
        submission(expected_revision=1, page_content="合成第二版内容")), [])["revision"] == 2
    assert store.read(principal(), 101, 201, "page-a", 1) == original
    assert store.read(principal(), 101, 201, "page-a", 2)["screenshots"] == []
    with pytest.raises(RevisionConflict):
        store.submit(principal(), payload, [])
    with pytest.raises(RevisionConflict):
        store.submit(principal(), LandingSubmission.model_validate(
            submission(expected_revision=2, landing_url="https://example.invalid/other")), [])
    for bad in (principal(role="customer"), principal(accounts=frozenset({(101, 999)})),
                principal(accounts=frozenset({(999, 201)})), principal(actor=" ")):
        with pytest.raises(ScopeDenied):
            store.submit(bad, payload, [])
        with pytest.raises(ScopeDenied):
            store.read(bad, 101, 201, "page-a", 1)


def test_attachments_atomic_and_single_page(tmp_path):
    store = SubmissionStore(tmp_path / "store.sqlite")
    payload = LandingSubmission.model_validate(submission())
    for shots in ([Screenshot("page-b", "shot.png", "image/png", png())],
                  [Screenshot("page-a", "shot.png", "image/png", png()),
                   Screenshot("page-a", "bad.pdf", "application/pdf", b"bad")]):
        with pytest.raises(ValueError):
            store.submit(principal(), payload, shots)
        assert store.read(principal(), 101, 201, "page-a", 1) is None
    store.submit(principal(), payload, [])
    store.submit(principal(), LandingSubmission.model_validate(submission(
        landing_page_id="page-b", landing_url="https://example.invalid/b")), [])
    assert store.read(principal(), 101, 201, "page-b", 1)["screenshots"] == []


def test_parallel_version_conflict(tmp_path):
    store = SubmissionStore(tmp_path / "store.sqlite")
    payload = LandingSubmission.model_validate(submission())
    def attempt(_):
        try:
            return store.submit(principal(), payload, [])["revision"]
        except RevisionConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str, pool.map(attempt, range(2)))) == ["1", "conflict"]


def test_multipart_api_and_scope(tmp_path):
    app = FastAPI()
    active = principal()
    def auth():
        if active is None:
            raise HTTPException(401, "未登录")
        return active
    app.include_router(create_router(SubmissionStore(tmp_path / "store.sqlite"), auth))
    with TestClient(app) as client:
        url = "/api/v1/sem/phase0/submissions"
        response = client.post(url, data={"metadata": json.dumps(submission())},
                               files=[("screenshots", ("shot.png", png(), "image/png"))])
        assert response.status_code == 201 and response.json()["screenshot_count"] == 1
        assert client.get(url + "/101/201/page-a/1").json()["screenshots"][0]["ocr_status"] == "not_connected"
        assert client.post(url, data={"metadata": json.dumps(submission())}).status_code == 409
        invalid = submission(page_content="do-not-echo-input", budget_cents=0)
        response = client.post(url, data={"metadata": json.dumps(invalid)})
        assert response.status_code == 422 and "do-not-echo-input" not in response.text
        active = principal(role="customer")
        assert client.post(url, data={"metadata": json.dumps(submission())}).status_code == 403
        assert client.get(url + "/101/201/page-a/1").status_code == 403
        active = None
        assert client.post(url, data={"metadata": json.dumps(submission())}).status_code == 401


def plan_and_config():
    plan = dict(budgets=[dict(row_id="project", parent_id=None, cents=10000, reserved_cents=1000,
                             currency="CNY", period="daily"),
                        dict(row_id="plan", parent_id="project", cents=9000, reserved_cents=0,
                             currency="CNY", period="daily")],
                texts=[dict(row_id="creative", limit_key="title", text="合成标题", source_refs=["synthetic:p1"],
                            source_confirmed=True)], negative_overlap_checked=True,
                online_facts_verified=True, conflicts_resolved=True)
    config = dict(version="synthetic-v1", platform_limits_verified=True, limits_evidence="synthetic-test-only",
                  text_limits={"title": dict(maximum=8, counting="ascii1_other2", evidence="synthetic-test-only")},
                  account_cap_cents=10000)
    return plan, config


def test_good_internal_rules_still_cannot_export():
    plan, config = plan_and_config()
    result = check_plan(CheckInput(**plan), RuleConfig(**config))
    assert result["passed"] and not result["execution_export_enabled"]
    assert result["customer_confirmation"] == "pending"


@pytest.mark.parametrize("change,rule", [
    ("cap", "account_cap"), ("sum", "budget_tree"), ("period", "budget_tree"),
    ("duplicate", "budget_tree"), ("orphan", "budget_tree"), ("cycle", "budget_tree"),
    ("length", "text_length"), ("source", "source_complete"), ("source-review", "source_complete"),
    ("unknown-limit", "text_length"), ("unknown-platform", "platform_limits"),
    ("unknown-cap", "account_cap"), ("negative", "negative_overlap"),
    ("online", "online_facts"), ("conflict", "conflicts"),
])
def test_missing_or_over_cap_is_blocked(change, rule):
    plan, config = plan_and_config()
    if change == "cap": config["account_cap_cents"] = 9999
    if change == "sum": plan["budgets"][1]["cents"] += 1
    if change == "period": plan["budgets"][1]["period"] = "total"
    if change == "duplicate": plan["budgets"].append(copy.deepcopy(plan["budgets"][1]))
    if change == "orphan": plan["budgets"][1]["parent_id"] = "absent"
    if change == "cycle": plan["budgets"][0]["parent_id"] = "plan"
    if change == "length": plan["texts"][0]["text"] += "越限"
    if change == "source": plan["texts"][0]["source_refs"] = []
    if change == "source-review": plan["texts"][0]["source_confirmed"] = False
    if change == "unknown-limit": config["text_limits"] = {}
    if change == "unknown-platform": config["platform_limits_verified"] = False
    if change == "unknown-cap": config["account_cap_cents"] = None
    if change == "negative": plan["negative_overlap_checked"] = None
    if change == "online": plan["online_facts_verified"] = False
    if change == "conflict": plan["conflicts_resolved"] = None
    result = check_plan(CheckInput(**plan), RuleConfig(**config))
    assert not result["passed"] and rule in {issue["rule"] for issue in result["issues"]}


def test_template_export_permanently_closed(tmp_path):
    sample = synthetic_sample()
    assert sample["notice"] == "内部演练/不可上传百度" and sample["official_headers"] is None
    assert not sample["execution_export_enabled"]
    write_internal_sample(tmp_path / "sample.json")
    assert json.loads((tmp_path / "sample.json").read_text(encoding="utf-8")) == sample
    with pytest.raises(ValueError):
        write_internal_sample(tmp_path / "sample.csv")
    with pytest.raises(PermissionError):
        export_baidu_execution_file(approved=True)

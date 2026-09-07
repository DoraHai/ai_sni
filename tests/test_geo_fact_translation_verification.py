import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.geo.content.routes import update_fact, verify_fact
from app.geo.content.schemas import FactUpdate, FactVerifyRequest


SOURCE = "The MAXXDRIVE XT industrial gear unit has a heavily ribbed housing, axial fan and air guide cover."
TRANSLATION = "MAXXDRIVE XT 工业齿轮箱配有加强肋壳体、轴向风扇和导风罩。"


def fact(**overrides):
    values = {
        "id": 3,
        "tenant_id": 7,
        "title": "MAXXDRIVE XT cooling structure",
        "statement": SOURCE,
        "fact_type": "product",
        "source_name": "NORD product page",
        "source_url": "https://example.com/maxxdrive",
        "observed_at": None,
        "expires_at": None,
        "trust_level": "verified",
        "status": "active",
        "meta": {},
        "author_name": None,
        "import_batch_id": None,
        "business_id": None,
        "created_by": 9,
        "created_at": None,
        "updated_at": None,
    }
    values.update(overrides)
    return NS(**values)


def context():
    return NS(user_id=42, ensure_tenant=lambda tenant_id: None)


def session():
    return NS(
        scalars=AsyncMock(return_value=[]),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )


def test_verify_fact_records_translation_bound_to_exact_source_and_reviewer():
    row = fact()
    db = session()
    req = FactVerifyRequest(
        excerpt=SOURCE,
        excerpt_locator="product page specification",
        verified_translation=TRANSLATION,
        expected_source_statement=SOURCE,
        expected_source_name="NORD product page",
        expected_source_url="https://example.com/maxxdrive",
    )

    async def exercise():
        with patch("app.geo.content.routes._get_fact", AsyncMock(return_value=row)):
            return await verify_fact(3, req, 7, context(), db)

    result = asyncio.run(exercise())
    record = row.meta["verified_translations"][0]
    assert record["fact_id"] == 3
    assert record["text"] == TRANSLATION
    assert record["source_statement"] == SOURCE
    assert record["status"] == "verified"
    assert record["verified_by"] == 42
    assert record["verified_at"]
    assert result["meta"]["verified_translations"] == [record]


def test_verify_fact_rejects_same_language_as_translation():
    row = fact()
    req = FactVerifyRequest(
        excerpt=SOURCE,
        excerpt_locator="product page specification",
        verified_translation="The MAXXDRIVE XT unit has an axial fan.",
        expected_source_statement=SOURCE,
        expected_source_name="NORD product page",
        expected_source_url="https://example.com/maxxdrive",
    )

    async def exercise():
        with patch("app.geo.content.routes._get_fact", AsyncMock(return_value=row)):
            return await verify_fact(3, req, 7, context(), session())

    with pytest.raises(HTTPException, match="不同语言"):
        asyncio.run(exercise())


def test_reverify_without_translation_removes_previous_translation():
    row = fact(
        meta={
            "verified_translations": [
                {
                    "text": TRANSLATION,
                    "source_statement": SOURCE,
                    "status": "verified",
                    "verified_at": "2026-09-07T00:00:00",
                    "verified_by": 4,
                }
            ]
        }
    )
    req = FactVerifyRequest(
        excerpt=SOURCE,
        excerpt_locator="product page specification",
        verified_translation=None,
    )

    async def exercise():
        with patch("app.geo.content.routes._get_fact", AsyncMock(return_value=row)):
            await verify_fact(3, req, 7, context(), session())

    asyncio.run(exercise())
    assert "verified_translations" not in row.meta


def test_legacy_reverify_request_does_not_silently_delete_translation():
    record = {
        "fact_id": 3,
        "text": TRANSLATION,
        "source_statement": SOURCE,
        "status": "verified",
        "verified_at": "2026-09-07T00:00:00",
        "verified_by": 4,
    }
    row = fact(meta={"verified_translations": [record]})
    req = FactVerifyRequest(
        excerpt=SOURCE,
        excerpt_locator="product page specification",
    )

    async def exercise():
        with patch("app.geo.content.routes._get_fact", AsyncMock(return_value=row)):
            await verify_fact(3, req, 7, context(), session())

    asyncio.run(exercise())
    assert row.meta["verified_translations"] == [record]


def test_stale_translation_snapshot_is_rejected_without_writing_metadata():
    changed = "The MAXXDRIVE XT industrial gear unit does not have an axial fan."
    row = fact(statement=changed, meta={"classification": "manual"})
    db = session()
    req = FactVerifyRequest(
        excerpt="The MAXXDRIVE XT industrial gear unit",
        excerpt_locator="product page specification",
        verified_translation=TRANSLATION,
        expected_source_statement=SOURCE,
        expected_source_name="NORD product page",
        expected_source_url="https://example.com/maxxdrive",
    )

    async def exercise():
        with patch("app.geo.content.routes._get_fact", AsyncMock(return_value=row)):
            await verify_fact(3, req, 7, context(), db)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(exercise())
    assert exc.value.status_code == 409
    assert row.meta == {"classification": "manual"}
    db.commit.assert_not_awaited()
    db.refresh.assert_awaited_once_with(row, with_for_update=True)


def test_patch_cannot_inject_verification_or_translation_metadata():
    row = fact(meta={"classification": "manual"})
    req = FactUpdate(
        meta={
            "classification": "updated",
            "verified_by": 999,
            "verified_translations": [{"text": "伪造译文"}],
        }
    )

    async def exercise():
        with patch("app.geo.content.routes._get_fact", AsyncMock(return_value=row)):
            await update_fact(3, req, 7, context(), session())

    asyncio.run(exercise())
    assert row.meta == {"classification": "updated"}


def test_changing_statement_invalidates_fact_and_translation_verification():
    row = fact(
        meta={
            "classification": "manual",
            "verification": {"verified_at": "2026-09-07T00:00:00"},
            "verified_translations": [{"text": TRANSLATION}],
        }
    )
    req = FactUpdate(statement="The MAXXDRIVE XT industrial gear unit has an axial fan.")

    async def exercise():
        with patch("app.geo.content.routes._get_fact", AsyncMock(return_value=row)):
            await update_fact(3, req, 7, context(), session())

    asyncio.run(exercise())
    assert row.trust_level == "needs_review"
    assert row.meta == {"classification": "manual"}


@pytest.mark.parametrize("field,value", [
    ("source_name", "Updated official source"),
    ("source_url", "https://example.com/new-source"),
])
def test_changing_source_identity_invalidates_verification(field, value):
    row = fact(meta={"verification": {"verified_at": "2026-09-07"}, "verified_translations": [{"text": TRANSLATION}]})
    req = FactUpdate(**{field: value})

    async def exercise():
        with patch("app.geo.content.routes._get_fact", AsyncMock(return_value=row)):
            await update_fact(3, req, 7, context(), session())

    asyncio.run(exercise())
    assert row.trust_level == "needs_review"
    assert row.meta == {}

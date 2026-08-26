import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api.seo import (
    KeywordCreate,
    KeywordImport,
    KeywordUpdate,
    _keyword_site_move_blockers,
    import_seo_keywords,
    update_seo_keyword,
)
from app.models.seo import SeoKeywordAsset
from app.security.auth import AuthContext


def _context() -> AuthContext:
    return AuthContext(
        user_id=7,
        username="seo-operator",
        role_name="运营",
        tenant_id=1,
        permissions={"seo.keywords": "edit"},
    )


def test_keyword_site_move_blockers_reports_all_seo_dependencies() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[2, 1, 3, 4])

    result = asyncio.run(_keyword_site_move_blockers(session, 11))

    assert result == {
        "rank_snapshots": 2,
        "serp_results": 1,
        "site_pages": 3,
        "content_assets": 4,
    }


def test_keyword_site_cannot_be_cleared() -> None:
    keyword = SeoKeywordAsset(id=11, tenant_id=1, site_id=8, keyword="SEO")
    session = AsyncMock()

    with patch("app.api.seo._keyword_for_update", new=AsyncMock(return_value=keyword)):
        with pytest.raises(Exception) as exc:
            asyncio.run(
                update_seo_keyword(
                    11,
                    1,
                    KeywordUpdate(site_id=None),
                    session,
                )
            )

    assert getattr(exc.value, "status_code", None) == 400
    session.commit.assert_not_awaited()


def test_keyword_with_dependencies_cannot_move_sites() -> None:
    keyword = SeoKeywordAsset(id=11, tenant_id=1, site_id=8, keyword="SEO")
    session = AsyncMock()

    with (
        patch("app.api.seo._keyword_for_update", new=AsyncMock(return_value=keyword)),
        patch("app.api.seo._seo_site", new=AsyncMock()),
        patch(
            "app.api.seo._keyword_site_move_blockers",
            new=AsyncMock(return_value={"rank_snapshots": 2}),
        ),
    ):
        with pytest.raises(Exception) as exc:
            asyncio.run(
                update_seo_keyword(
                    11,
                    1,
                    KeywordUpdate(site_id=9),
                    session,
                )
            )

    assert getattr(exc.value, "status_code", None) == 409
    assert keyword.site_id == 8
    session.commit.assert_not_awaited()


def test_unreferenced_keyword_can_move_to_valid_site() -> None:
    keyword = SeoKeywordAsset(id=11, tenant_id=1, site_id=8, keyword="SEO")
    session = AsyncMock()

    with (
        patch("app.api.seo._keyword_for_update", new=AsyncMock(return_value=keyword)),
        patch("app.api.seo._seo_site", new=AsyncMock()),
        patch(
            "app.api.seo._keyword_site_move_blockers",
            new=AsyncMock(return_value={}),
        ),
    ):
        result = asyncio.run(
            update_seo_keyword(
                11,
                1,
                KeywordUpdate(site_id=9),
                session,
            )
        )

    assert keyword.site_id == 9
    assert result["site_id"] == 9
    session.commit.assert_awaited_once_with()


def test_keyword_import_rejects_item_for_another_site() -> None:
    request = KeywordImport(
        tenant_id=1,
        site_id=8,
        items=[KeywordCreate(tenant_id=1, site_id=9, keyword="SEO")],
    )
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=[])

    with (
        patch("app.api.seo._tenant", new=AsyncMock()),
        patch("app.api.seo._seo_site", new=AsyncMock()),
    ):
        with pytest.raises(Exception) as exc:
            asyncio.run(import_seo_keywords(request, session, _context()))

    assert getattr(exc.value, "status_code", None) == 400
    session.commit.assert_not_awaited()

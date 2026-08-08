from datetime import datetime

import pytest
from pydantic import ValidationError

from app.api.seo import KeywordCreate, RankSnapshotCreate, SitePageImport, _keyword_payload
from app.models.seo import SeoKeywordAsset, SeoRankSnapshot, SeoSitePage
from app.permissions import CLIENT_PERMS, MENU_KEYS, OPERATOR_PERMS
from app.security.auth import AuthContext, _required


def test_seo_permissions_are_registered_for_all_roles() -> None:
    assert {"seo.keywords", "seo.site"} <= MENU_KEYS
    assert OPERATOR_PERMS["seo.keywords"] == "edit"
    assert OPERATOR_PERMS["seo.site"] == "edit"
    assert CLIENT_PERMS["seo.keywords"] == "view"
    assert CLIENT_PERMS["seo.site"] == "view"


@pytest.mark.parametrize(
    ("path", "method", "permission", "needs_edit"),
    [
        ("/api/v1/seo/keywords", "GET", "seo.keywords", False),
        ("/api/v1/seo/keywords", "POST", "seo.keywords", True),
        ("/api/v1/seo/rank-snapshots", "POST", "seo.keywords", True),
        ("/api/v1/seo/site-pages", "GET", "seo.site", False),
        ("/api/v1/seo/site-pages/1/audit", "POST", "seo.site", True),
    ],
)
def test_seo_routes_map_to_expected_permissions(
    path: str, method: str, permission: str, needs_edit: bool
) -> None:
    permissions, edit = _required(path, method)
    assert permissions == {permission}
    assert edit is needs_edit


def test_tenant_bound_context_rejects_cross_tenant_write() -> None:
    context = AuthContext(
        user_id=7,
        username="operator",
        role_name="运营",
        tenant_id=12,
        permissions={"seo.keywords": "edit"},
    )
    context.ensure_tenant(12)
    with pytest.raises(Exception) as exc:
        context.ensure_tenant(13)
    assert getattr(exc.value, "status_code", None) == 403


def test_keyword_and_rank_input_validation() -> None:
    keyword = KeywordCreate(
        tenant_id=1,
        keyword="CRM 系统",
        difficulty=68,
        monthly_volume=1200,
        priority="P0",
    )
    assert keyword.keyword == "CRM 系统"
    with pytest.raises(ValidationError):
        KeywordCreate(tenant_id=1, keyword="CRM", difficulty=101)
    with pytest.raises(ValidationError):
        RankSnapshotCreate(
            tenant_id=1,
            keyword_id=2,
            engine="baidu",
            rank=101,
        )


def test_site_page_import_requires_at_least_one_url() -> None:
    with pytest.raises(ValidationError):
        SitePageImport(tenant_id=1, urls=[])


def test_rank_delta_uses_smaller_rank_as_improvement() -> None:
    now = datetime(2026, 8, 9, 12, 0)
    keyword = SeoKeywordAsset(
        id=1,
        tenant_id=2,
        keyword="SEO 服务",
        priority="P1",
        status="active",
        source="manual",
        created_at=now,
        updated_at=now,
    )
    latest = SeoRankSnapshot(
        id=11,
        tenant_id=2,
        keyword_id=1,
        engine="baidu",
        device="desktop",
        region="全国",
        subject_type="own",
        rank=4,
        source="manual",
        checked_at=now,
    )
    previous = SeoRankSnapshot(
        id=10,
        tenant_id=2,
        keyword_id=1,
        engine="baidu",
        device="desktop",
        region="全国",
        subject_type="own",
        rank=9,
        source="manual",
        checked_at=now,
    )
    payload = _keyword_payload(keyword, latest, previous)
    assert payload["latest_rank"] == 4
    assert payload["rank_delta"] == 5


def test_models_use_separate_seo_tables() -> None:
    assert SeoKeywordAsset.__tablename__ == "seo_keyword_assets"
    assert SeoRankSnapshot.__tablename__ == "seo_rank_snapshots"
    assert SeoSitePage.__tablename__ == "seo_site_pages"

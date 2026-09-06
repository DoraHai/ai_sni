"""Pure-query GEO question catalog for cockpit integrations."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.read_session import geo_read_session
from app.geo.tenant_scope import require_geo_read_entitlement
from app.models import GeoOptimizationBusiness, GeoOptimizationUnit, GeoPrompt
from app.security.auth import AuthContext, require_scoped_auth


router = APIRouter(
    prefix="/integration/read",
    tags=["GEO 工作台只读接口"],
    dependencies=[Depends(require_geo_read_entitlement)],
)


class QuestionRef(BaseModel):
    module: str = "geo"
    type: str
    id: int


class QuestionScopeRef(QuestionRef):
    name: str
    status: str


class QuestionReadItem(BaseModel):
    ref: QuestionRef
    current_text: str
    language: str
    status: str
    question_source: str
    question_group: str | None
    market: str
    is_brand_probe: bool
    priority: int
    tags: list[str]
    unit_ref: QuestionScopeRef | None
    business_ref: QuestionScopeRef | None
    created_at: datetime
    updated_at: datetime


class QuestionPagination(BaseModel):
    limit: int
    has_more: bool
    next_before_id: int | None


class QuestionReadPage(BaseModel):
    tenant_id: int
    evaluated_at: datetime
    pagination: QuestionPagination
    items: list[QuestionReadItem]


def build_question_query(
    *,
    tenant_id: int,
    limit: int,
    before_id: int | None = None,
    status: str | None = None,
    is_brand_probe: bool | None = None,
    unit_id: int | None = None,
    business_id: int | None = None,
) -> Select:
    """Build a tenant-scoped, stable keyset query; fetch one row for has_more."""
    stmt = (
        select(GeoPrompt, GeoOptimizationUnit, GeoOptimizationBusiness)
        .outerjoin(
            GeoOptimizationUnit,
            and_(
                GeoPrompt.unit_id == GeoOptimizationUnit.id,
                GeoOptimizationUnit.tenant_id == tenant_id,
            ),
        )
        .outerjoin(
            GeoOptimizationBusiness,
            and_(
                GeoOptimizationUnit.business_id == GeoOptimizationBusiness.id,
                GeoOptimizationBusiness.tenant_id == tenant_id,
            ),
        )
        .where(GeoPrompt.tenant_id == tenant_id)
    )
    if before_id is not None:
        stmt = stmt.where(GeoPrompt.id < before_id)
    if status is not None:
        stmt = stmt.where(GeoPrompt.status == status)
    if is_brand_probe is not None:
        stmt = stmt.where(GeoPrompt.is_brand_probe.is_(is_brand_probe))
    if unit_id is not None:
        stmt = stmt.where(GeoPrompt.unit_id == unit_id)
    if business_id is not None:
        stmt = stmt.where(GeoOptimizationUnit.business_id == business_id)
    return stmt.order_by(GeoPrompt.id.desc()).limit(limit + 1)


def _scope_ref(value, ref_type: str) -> QuestionScopeRef | None:
    if value is None:
        return None
    return QuestionScopeRef(type=ref_type, id=value.id, name=value.name, status=value.status)


def question_page(
    rows: list[tuple[GeoPrompt, GeoOptimizationUnit | None, GeoOptimizationBusiness | None]],
    *,
    tenant_id: int,
    limit: int,
) -> QuestionReadPage:
    """Serialize one page without exposing owner ids, notes, or task ids."""
    has_more = len(rows) > limit
    included = rows[:limit]
    items = [
        QuestionReadItem(
            ref=QuestionRef(type="question", id=prompt.id),
            current_text=prompt.question,
            language=prompt.language,
            status=prompt.status,
            question_source=prompt.source,
            question_group=prompt.question_group,
            market=prompt.market,
            is_brand_probe=prompt.is_brand_probe,
            priority=prompt.priority,
            tags=[str(tag) for tag in (prompt.tags or []) if str(tag).strip()],
            unit_ref=_scope_ref(unit, "optimization_unit"),
            business_ref=_scope_ref(business, "optimization_business"),
            created_at=prompt.created_at,
            updated_at=prompt.updated_at,
        )
        for prompt, unit, business in included
    ]
    return QuestionReadPage(
        tenant_id=tenant_id,
        evaluated_at=datetime.now(timezone.utc),
        pagination=QuestionPagination(
            limit=limit,
            has_more=has_more,
            next_before_id=items[-1].ref.id if has_more and items else None,
        ),
        items=items,
    )


@router.get("/questions", response_model=QuestionReadPage)
async def list_questions(
    tenant_id: int,
    status: str | None = Query(None, min_length=1, max_length=32),
    is_brand_probe: bool | None = None,
    unit_id: int | None = Query(None, ge=1),
    business_id: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = Query(None, ge=1),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(geo_read_session),
) -> QuestionReadPage:
    """Return the question catalog without initializing configuration or executing work."""
    ctx.ensure_tenant(tenant_id)
    result = await session.execute(
        build_question_query(
            tenant_id=tenant_id,
            limit=limit,
            before_id=before_id,
            status=status,
            is_brand_probe=is_brand_probe,
            unit_id=unit_id,
            business_id=business_id,
        )
    )
    return question_page(result.all(), tenant_id=tenant_id, limit=limit)

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import (
    adjustments_verify_router,
    alerts_router,
    assistant_router,
    auth_router,
    customer_profile_router,
    dashboard_router,
    expansion_router,
    keywords_router,
    leads_router,
    manage_router,
    negatives_router,
    ocpc_router,
    onboarding_builder_router,
    operations_router,
    reports_router,
    roles_router,
    structure_router,
    suggestions_router,
    insights_router,
    users_router,
    writeback_router,
    search_terms_router,
    geo_router,
)
from app.baidu import BaiduAPIClient, BaiduAPIError
from app.baidu.services import AccountService
from app.baidu.sync import (
    sync_operation_records_for_account,
    sync_adgroups_for_account,
    sync_campaigns_for_account,
    sync_keyword_report_for_account,
    sync_keyword_dimension_reports_for_account,
    sync_keywords_for_account,
    sync_ocpc_packages_for_account,
    sync_planner_candidates_for_account,
    sync_price_strategies_for_account,
    sync_query_candidates_for_account,
    sync_url_candidates_for_account,
)
from app.classification import reclassify_keywords
from app.config import get_settings
from app.database import async_session_factory, engine, get_session
from app.models import BaiduAccount, Keyword, Tenant
from app.scheduler import (
    refresh_keyword_workbench_snapshot,
    shutdown_scheduler,
    start_scheduler,
)
from app.security.auth import require_scoped_auth
from app.security.crypto import encrypt

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("sem-backend")

app = FastAPI(title="SEM 智投平台后端", version="0.3.0")

# 原型页（file:// 或其他域名）直连接口需要 CORS。API Key 走自定义头/查询参数，不涉及 credentials。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(dashboard_router)
app.include_router(alerts_router)
app.include_router(keywords_router)
app.include_router(structure_router)
app.include_router(operations_router)
app.include_router(expansion_router)
app.include_router(negatives_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(roles_router)
app.include_router(suggestions_router)
app.include_router(insights_router)
app.include_router(reports_router)
app.include_router(customer_profile_router)
app.include_router(adjustments_verify_router)
app.include_router(writeback_router)
app.include_router(search_terms_router)
app.include_router(leads_router)
app.include_router(ocpc_router)
app.include_router(manage_router)
app.include_router(assistant_router)
app.include_router(onboarding_builder_router)
app.include_router(geo_router)


@app.get("/health")
async def health() -> dict:
    db_status = "ok"
    db_error: str | None = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = "error"
        db_error = str(e)

    return {
        "service": "sem-backend",
        "env": settings.app_env,
        "db": db_status,
        "db_error": db_error,
    }


@app.get("/api/baidu/account/info")
async def baidu_account_info() -> dict:
    """P0 验证路由：用 env 自授权 token 调一次 getAccountInfo。"""
    client = BaiduAPIClient(
        username=settings.baidu_default_username,
        access_token=settings.baidu_self_access_token,
    )
    service = AccountService(client)
    try:
        data = await service.get_account_info()
        return {"status": "ok", "data": data}
    except BaiduAPIError as e:
        return {
            "status": "error",
            "code": e.code,
            "message": e.message,
            "token_invalid": e.is_token_invalid,
        }


# ============================================================
# Admin 接口：一次性初始化 + 手动触发
# 鉴权：ADMIN_API_KEY（X-API-Key 请求头），见 app/security/api_key.py
# ============================================================


@app.post(
    "/api/v1/admin/init-self-auth-account", dependencies=[Depends(require_scoped_auth)]
)
async def init_self_auth_account(
    tenant_name: str = Query(..., description="租户名，比如 苏尔寿"),
    monthly_budget: float | None = Query(None, description="月预算（元）"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """从 env 的 BAIDU_DEFAULT_* 自授权配置 → 建 tenant + baidu_account。

    幂等：tenant_name 已存在就复用，access_token 重复就更新。
    """
    # 找/建 tenant
    tenant = await session.scalar(select(Tenant).where(Tenant.name == tenant_name))
    if tenant is None:
        tenant = Tenant(name=tenant_name)
        if monthly_budget is not None:
            tenant.monthly_budget = monthly_budget
        session.add(tenant)
        await session.flush()

    # 找/建 baidu_account
    existing = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant.id,
            BaiduAccount.baidu_username == settings.baidu_default_username,
        )
    )
    expires_at = datetime.fromisoformat(settings.baidu_self_token_expires_at)

    if existing is None:
        acc = BaiduAccount(
            tenant_id=tenant.id,
            baidu_username=settings.baidu_default_username,
            baidu_ucid=settings.baidu_default_ucid,
            access_token_encrypted=encrypt(settings.baidu_self_access_token),
            expires_at=expires_at,
            auth_mode="self",
            status="active",
        )
        session.add(acc)
        action = "created"
    else:
        existing.access_token_encrypted = encrypt(settings.baidu_self_access_token)
        existing.expires_at = expires_at
        existing.status = "active"
        acc = existing
        action = "updated"

    await session.commit()
    await session.refresh(acc)

    return {
        "status": "ok",
        "action": action,
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "baidu_account_id": acc.id,
        "baidu_username": acc.baidu_username,
        "expires_at": acc.expires_at.isoformat(),
    }


@app.post(
    "/api/v1/admin/fetch-keyword-report", dependencies=[Depends(require_scoped_auth)]
)
async def fetch_keyword_report(
    tenant_id: int = Query(..., description="本地租户 ID"),
    target_date: date = Query(..., description="目标日期 YYYY-MM-DD"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """手动触发：拉某租户某天的关键词报告并入库。"""
    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active"
        )
    )
    if acc is None:
        raise HTTPException(
            404, f"tenant_id={tenant_id} 没有 active 的 baidu_account"
        )

    try:
        n = await sync_keyword_report_for_account(session, acc, target_date)
        dimension_rows = await sync_keyword_dimension_reports_for_account(session, acc, target_date)
    except BaiduAPIError as e:
        return {
            "status": "error",
            "code": e.code,
            "message": e.message,
            "token_invalid": e.is_token_invalid,
        }

    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "date": target_date.isoformat(),
        "rows_written": n,
        "dimension_rows_written": dimension_rows,
    }


@app.post(
    "/api/v1/admin/fetch-keyword-dimension-reports",
    dependencies=[Depends(require_scoped_auth)],
)
async def fetch_keyword_dimension_reports(
    tenant_id: int = Query(..., description="本地租户 ID"),
    start_date: date = Query(..., description="起始日期 YYYY-MM-DD"),
    end_date: date = Query(..., description="截止日期 YYYY-MM-DD"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """手动触发：按日期范围补拉关键词地域/小时效果报告。"""
    if start_date > end_date:
        raise HTTPException(400, "start_date 不能晚于 end_date")
    if (end_date - start_date).days > 93:
        raise HTTPException(400, "一次最多同步 94 天，请分批执行")

    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active"
        )
    )
    if acc is None:
        raise HTTPException(
            404, f"tenant_id={tenant_id} 没有 active 的 baidu_account"
        )

    result: dict[str, dict[str, int]] = {}
    cur = start_date
    try:
        while cur <= end_date:
            result[cur.isoformat()] = await sync_keyword_dimension_reports_for_account(
                session, acc, cur
            )
            cur += timedelta(days=1)
    except BaiduAPIError as e:
        return {
            "status": "error",
            "code": e.code,
            "message": e.message,
            "token_invalid": e.is_token_invalid,
            "partial": result,
        }

    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days": len(result),
        "rows_written": result,
    }


@app.post("/api/v1/admin/sync-keywords", dependencies=[Depends(require_scoped_auth)])
async def sync_keywords(
    tenant_id: int = Query(..., description="本地租户 ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """手动触发：计划/单元层级 + 关键词维度同步 + 5 类分级重算（每日 02:00 也会自动跑）。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active"
        )
    )
    if acc is None:
        raise HTTPException(404, f"tenant_id={tenant_id} 没有 active 的 baidu_account")

    try:
        n_camp = await sync_campaigns_for_account(session, acc)
        n_adg = await sync_adgroups_for_account(session, acc)
        n_kw = await sync_keywords_for_account(session, acc)
        n_strat = await sync_price_strategies_for_account(session, acc)
        n_ocpc = await sync_ocpc_packages_for_account(session, acc)
    except BaiduAPIError as e:
        return {
            "status": "error",
            "code": e.code,
            "message": e.message,
            "token_invalid": e.is_token_invalid,
        }
    counts = await reclassify_keywords(session, tenant)
    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "campaigns_synced": n_camp,
        "adgroups_synced": n_adg,
        "keywords_synced": n_kw,
        "price_strategies_synced": n_strat,
        "ocpc_packages_synced": n_ocpc,
        "category_counts": counts,
    }


@app.post(
    "/api/v1/admin/refresh-keyword-workbench",
    dependencies=[Depends(require_scoped_auth)],
)
async def refresh_keyword_workbench(
    tenant_id: int = Query(..., description="本地租户 ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """立即刷新当前客户的当日报告、层级、关键词和出价策略数据。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id,
            BaiduAccount.status == "active",
        )
    )
    if acc is None:
        raise HTTPException(404, f"tenant_id={tenant_id} 没有 active 的 baidu_account")

    try:
        return await refresh_keyword_workbench_snapshot(
            session, tenant, acc, datetime.now(ZoneInfo("Asia/Shanghai")).date()
        )
    except BaiduAPIError as exc:
        return {
            "status": "error",
            "code": exc.code,
            "message": exc.message,
            "token_invalid": exc.is_token_invalid,
        }


@app.post("/api/v1/admin/sync-operation-records", dependencies=[Depends(require_scoped_auth)])
async def sync_operation_records(
    tenant_id: int = Query(..., description="本地租户 ID"),
    start_date: date | None = Query(None, description="默认 90 天前（一星客户回溯上限）"),
    end_date: date | None = Query(None, description="默认今天"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """手动触发操作记录同步（调价台账回灌入口，只读百度）。

    首次接入建议拉满回溯窗口（按客户星级 3-12 个月），之后每日 02:00 自动增量。
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active"
        )
    )
    if acc is None:
        raise HTTPException(404, f"tenant_id={tenant_id} 没有 active 的 baidu_account")

    end = end_date or date.today()
    start = start_date or end - timedelta(days=90)
    if start > end:
        raise HTTPException(400, "start_date 不能晚于 end_date")

    try:
        n = await sync_operation_records_for_account(session, acc, start, end)
    except BaiduAPIError as e:
        return {
            "status": "error",
            "code": e.code,
            "message": e.message,
            "token_invalid": e.is_token_invalid,
        }
    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "records_fetched": n,
    }


@app.post("/api/v1/admin/sync-expansion", dependencies=[Depends(require_scoped_auth)])
async def sync_expansion(
    tenant_id: int = Query(..., description="本地租户 ID"),
    seeds: str | None = Query(
        None, description="种子词，逗号分隔（最多 20 个）；不传则自动取累计展现最高的重点/一般词"
    ),
    max_num: int = Query(300, ge=1, le=1000, description="每个种子词的推荐词上限"),
    query_days: int = Query(30, ge=1, le=91, description="搜索词报告回看天数（上限 91）"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """手动触发拓词候选同步（规划师 + 搜索词转，🚫 只读百度不写回）。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active"
        )
    )
    if acc is None:
        raise HTTPException(404, f"tenant_id={tenant_id} 没有 active 的 baidu_account")

    if seeds:
        seed_list = list(dict.fromkeys(s.strip() for s in seeds.split(",") if s.strip()))[:20]
    else:
        # 默认种子：累计展现最高的重点/一般词（KRService 一次一个种子词，控制调用量取 10 个）。
        # 同一字面可能对应多个关键词 ID（不同单元/匹配方式），多取再按字面去重（生产实测 2026-06-12）
        texts = (
            await session.scalars(
                select(Keyword.keyword)
                .where(
                    Keyword.tenant_id == tenant_id,
                    Keyword.category.in_(["focus", "normal"]),
                    Keyword.keyword.isnot(None),
                )
                .order_by(Keyword.total_impression.desc())
                .limit(40)
            )
        ).all()
        seed_list = list(dict.fromkeys(t.strip() for t in texts if t.strip()))[:10]
    if not seed_list:
        seed_list = [t for t in (tenant.brand_terms or []) if t] or [tenant.name]

    end = date.today()
    start = end - timedelta(days=query_days - 1)
    try:
        n_planner = await sync_planner_candidates_for_account(
            session, acc, seed_list, max_num
        )
        n_query = await sync_query_candidates_for_account(session, acc, start, end)
    except BaiduAPIError as e:
        return {
            "status": "error",
            "code": e.code,
            "message": e.message,
            "token_invalid": e.is_token_invalid,
        }
    # 同步完顺带跑一次 AI 语义评估（治通用词噪音）。未配 DeepSeek 时内部降级返回 enabled=false，
    # AI 失败不影响同步结果——新候选默认只评未评估过的。
    from app.ai.expansion_eval import evaluate_candidates_for_tenant

    ai_eval = await evaluate_candidates_for_tenant(session, tenant)
    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "seeds": seed_list,
        "planner_candidates": n_planner,
        "query_candidates": n_query,
        "query_window": {"start": start.isoformat(), "end": end.isoformat()},
        "ai_eval": ai_eval,
    }


class SyncUrlWordsRequest(BaseModel):
    tenant_id: int
    urls: list[str] = Field(..., min_length=1, max_length=5)  # 原型口径：最多 5 个 URL


@app.post("/api/v1/admin/sync-url-words", dependencies=[Depends(require_scoped_auth)])
async def sync_url_words(
    req: SyncUrlWordsRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """URL 爬取拓词（自研提词 + getPvSearch 流量回查，🚫 只读百度不写回）。"""
    tenant = await session.get(Tenant, req.tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == req.tenant_id, BaiduAccount.status == "active"
        )
    )
    if acc is None:
        raise HTTPException(404, f"tenant_id={req.tenant_id} 没有 active 的 baidu_account")

    try:
        n, details = await sync_url_candidates_for_account(session, acc, req.urls)
    except BaiduAPIError as e:
        return {
            "status": "error",
            "code": e.code,
            "message": e.message,
            "token_invalid": e.is_token_invalid,
        }
    return {
        "status": "ok",
        "tenant_id": req.tenant_id,
        "candidates_written": n,
        "urls": details,
    }


# ============================================================
# 应用生命周期
# ============================================================


@app.on_event("startup")
async def on_startup() -> None:
    logger.info(
        "SEM 后端启动：env=%s base_url=%s default_user=%s",
        settings.app_env,
        settings.app_base_url,
        settings.baidu_default_username,
    )
    start_scheduler()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    shutdown_scheduler()

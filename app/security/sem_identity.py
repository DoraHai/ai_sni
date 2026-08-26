"""SEM 推广账户归属完整性检查。

当一个生效 UCID 同时出现在多个客户下时，宁可暂停访问，也不能继续返回可能属于
其他客户的投放数据。历史错误绑定不会直接删除；管理员可将错误账户标记为
``identity_conflict``，在保留审计线索的同时持续封锁该客户的旧数据。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BaiduAccount

SEM_IDENTITY_CONFLICT_STATUS = "identity_conflict"
SEM_IDENTITY_BLOCKED_CODE = "SEM_ACCOUNT_IDENTITY_CONFLICT"
SEM_IDENTITY_BLOCKED_MESSAGE = (
    "推广账户归属冲突，已暂停展示该客户的 SEM 数据，请联系超级管理员处理"
)


def public_sem_identity_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """返回前台安全状态，不暴露内部用于归属判定的 UCID。"""
    if state is None:
        return None
    return {
        "status": state.get("status"),
        "code": state.get("code"),
        "message": state.get("message"),
    }


def filter_identity_safe_active_accounts(
    accounts: Iterable[BaiduAccount],
) -> list[BaiduAccount]:
    """定时同步只处理唯一归属的 active 账户，冲突 UCID 全部失败关闭。"""
    active = [account for account in accounts if account.status == "active"]
    tenants_by_ucid: dict[int, set[int]] = {}
    for account in active:
        tenants_by_ucid.setdefault(account.baidu_ucid, set()).add(account.tenant_id)
    conflicted_ucids = {
        ucid for ucid, tenant_ids in tenants_by_ucid.items() if len(tenant_ids) > 1
    }
    return [account for account in active if account.baidu_ucid not in conflicted_ucids]


def evaluate_sem_identity_states(
    tenant_ids: Sequence[int],
    tenant_accounts: Iterable[BaiduAccount],
    active_accounts_for_ucids: Iterable[BaiduAccount],
) -> dict[int, dict[str, Any]]:
    """基于已加载账户计算每个客户的可访问状态，不泄露其他客户身份。"""
    ids = list(dict.fromkeys(int(tenant_id) for tenant_id in tenant_ids))
    local_by_tenant: dict[int, list[BaiduAccount]] = {tenant_id: [] for tenant_id in ids}
    for account in tenant_accounts:
        if account.tenant_id in local_by_tenant:
            local_by_tenant[account.tenant_id].append(account)

    active_tenants_by_ucid: dict[int, set[int]] = {}
    for account in active_accounts_for_ucids:
        if account.status != "active":
            continue
        active_tenants_by_ucid.setdefault(account.baidu_ucid, set()).add(account.tenant_id)

    states: dict[int, dict[str, Any]] = {}
    for tenant_id in ids:
        rows = local_by_tenant[tenant_id]
        quarantined_ucids = {
            account.baidu_ucid
            for account in rows
            if account.status == SEM_IDENTITY_CONFLICT_STATUS
        }
        active_ucids = {
            account.baidu_ucid for account in rows if account.status == "active"
        }
        cross_tenant_ucids = {
            ucid
            for ucid in active_ucids
            if len(active_tenants_by_ucid.get(ucid, set())) > 1
        }
        blocked_ucids = sorted(quarantined_ucids | cross_tenant_ucids)
        if blocked_ucids:
            states[tenant_id] = {
                "status": "blocked",
                "code": SEM_IDENTITY_BLOCKED_CODE,
                "message": SEM_IDENTITY_BLOCKED_MESSAGE,
                "ucids": [str(ucid) for ucid in blocked_ucids],
            }
        elif active_ucids:
            states[tenant_id] = {
                "status": "ok",
                "code": None,
                "message": None,
                "ucids": [],
            }
        else:
            states[tenant_id] = {
                "status": "unbound",
                "code": None,
                "message": "当前客户尚未绑定生效的百度推广账户",
                "ucids": [],
            }
    return states


async def load_sem_identity_states(
    session: AsyncSession,
    tenant_ids: Sequence[int],
    *,
    tenant_accounts: Sequence[BaiduAccount] | None = None,
) -> dict[int, dict[str, Any]]:
    """加载指定客户的账户，并检查相关 UCID 是否仍在其他客户下生效。"""
    ids = list(dict.fromkeys(int(tenant_id) for tenant_id in tenant_ids))
    if not ids:
        return {}

    local_rows = list(tenant_accounts) if tenant_accounts is not None else list(
        (
            await session.scalars(
                select(BaiduAccount).where(BaiduAccount.tenant_id.in_(ids))
            )
        ).all()
    )
    ucids = sorted({account.baidu_ucid for account in local_rows})
    active_matches: list[BaiduAccount] = []
    if ucids:
        active_matches = list(
            (
                await session.scalars(
                    select(BaiduAccount).where(
                        BaiduAccount.baidu_ucid.in_(ucids),
                        BaiduAccount.status == "active",
                    )
                )
            ).all()
        )
    return evaluate_sem_identity_states(ids, local_rows, active_matches)


async def ensure_sem_identity_access(session: AsyncSession, tenant_id: int) -> None:
    """冲突客户一律失败关闭，避免旧资产继续按 tenant_id 被读取或写回。"""
    state = (await load_sem_identity_states(session, [tenant_id]))[tenant_id]
    if state["status"] == "blocked":
        raise HTTPException(
            status_code=409,
            detail={
                "code": state["code"],
                "msg": state["message"],
            },
        )

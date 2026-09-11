"""调价回写编排：把 AI/人工确认后的出价写回百度（updateWord），逐条落台账。

安全分层：
  1. config.baidu_write_dry_run 演练开关（默认 True）——开启时 client 拦截不真发；
  2. 本模块业务校验——渐进调价 20% 硬上限 + 出价合法区间，越界直接拒绝；
  3. bid_writebacks 台账——旧价快照 + 目标价 + 是否演练 + 百度返回 + 操作人，全程留痕。
红线见 memory feedback-no-baidu-writeback：功能要做，但验证阶段绝不改乱线上真实出价。
"""
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu.client import BaiduAPIError, BaiduHTTPError, BaiduLiveWriteBlockedError
from app.baidu.regions import ALL_REGIONS_ID, region_ids
from app.baidu.services.account import AccountService
from app.baidu.services.adgroup import AdgroupService
from app.baidu.services.campaign import CampaignService
from app.baidu.services.keyword import KeywordService
from app.baidu.sync import _account_client
from app.baidu.writeback_approval import (
    ACTION_ACCOUNT_BUDGET,
    ACTION_ADGROUP_BID,
    ACTION_CAMPAIGN_BUDGET,
    ACTION_KEYWORD_BID,
    WritebackApprovalError,
    claim_approval,
    create_self_approved_approval,
)
from app.config import get_settings
from app.sem_live_write_policy import (
    SemLiveWritePolicyLimitError,
    resolve_live_write_decision,
)
from app.models import (
    Adgroup,
    BaiduAccount,
    BidWriteback,
    Campaign,
    Keyword,
    Suggestion,
    WritebackAction,
)

logger = logging.getLogger(__name__)

# 渐进调价硬上限（业务规则 2，前后端都拦）
MAX_CHANGE_PCT = 20.0
# 百度出价合法区间（文档 0066 指导价 [0,999.99)）
MIN_BID = 0.01
MAX_BID = 999.99
# 账户日预算合法区间（文档 0036 updateAccountInfo budget [50, 10000000]）
MIN_ACCOUNT_BUDGET = 50.0
MAX_ACCOUNT_BUDGET = 10000000.0
UNRESOLVED_REAL_STATUSES = {"pending", "reconcile"}
ADD_WORD_DEDUP_WINDOW = timedelta(hours=24)
CAMPAIGN_PAUSE_CONFLICT_ACTIONS = ("campaign_pause", "campaign_enable", "campaign_schedule")


class WritebackError(Exception):
    """回写前校验失败（业务拒绝，不调百度）。"""


def _boolean_audit_value(value: bool | None) -> int | None:
    return None if value is None else int(bool(value))


def _bounded_response_summary(value: Any, limit: int = 800) -> Any:
    """Return JSON-safe response evidence without ever truncating its container."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        encoded = json.dumps(str(value), ensure_ascii=False)
    if len(encoded) <= limit:
        return json.loads(encoded)
    return {
        "truncated": True,
        "originalChars": len(encoded),
        "preview": encoded[:limit],
    }


def _normalized_keyword_text(value: str | None) -> str:
    """Normalize surrounding whitespace and case for add-word duplicate checks."""
    return (value or "").strip().casefold()


async def _ensure_add_word_not_duplicate(
    session: AsyncSession,
    *,
    tenant_id: int,
    adgroup_id: int,
    word: str,
    dry_run: bool,
    exclude_record_id: int | None = None,
) -> None:
    """Reject existing or just-written keywords before invoking Baidu addWord.

    The caller already holds the target adgroup row lock, so concurrent requests
    for the same unit are serialized. The recent successful ledger check covers
    the interval before the next keyword dimension sync sees a newly added word.
    Recent dry-run rows block repeated rehearsals but never block a later live
    request. A recent live success blocks both modes until dimension sync catches up.
    """
    normalized = _normalized_keyword_text(word)
    existing_words = (
        await session.scalars(
            select(Keyword.keyword).where(
                Keyword.tenant_id == tenant_id,
                Keyword.adgroup_id == adgroup_id,
                func.lower(func.btrim(Keyword.keyword)) == normalized,
            )
        )
    ).all()
    if any(_normalized_keyword_text(existing) == normalized for existing in existing_words):
        raise WritebackError("目标单元已存在同名关键词，请勿重复加入")

    recent_statuses = ["success", *(["dry_run"] if dry_run else [])]
    write_conditions = [
        WritebackAction.tenant_id == tenant_id,
        WritebackAction.adgroup_id == adgroup_id,
        WritebackAction.action_type == "add_word",
        or_(
            WritebackAction.status.in_(["pending", "reconcile"]),
            and_(
                WritebackAction.status.in_(recent_statuses),
                WritebackAction.created_at >= func.now() - ADD_WORD_DEDUP_WINDOW,
            ),
        ),
        func.lower(func.btrim(WritebackAction.word)) == normalized,
    ]
    if exclude_record_id is not None:
        write_conditions.append(WritebackAction.id != exclude_record_id)
    recent_writes = (
        await session.scalars(
            select(WritebackAction.word).where(*write_conditions)
        )
    ).all()
    if any(_normalized_keyword_text(existing) == normalized for existing in recent_writes):
        raise WritebackError("该关键词已有待确认、演练或近期成功的加入记录，请先同步并核对台账")


@dataclass
class NegativeBatchWritebackResult:
    """批量否词的逐请求结果；同词多来源候选共享同一结果对象。"""

    word: str
    status: str
    error_msg: str | None = None
    no_op: bool = False
    record: WritebackAction | None = None


async def _claim_funds_approval(
    session: AsyncSession,
    *,
    approval_id: int | None,
    tenant_id: int,
    action_type: str,
    payload: dict,
    operator_user_id: int | None,
    dry_run: bool,
    confirmation: str | None = None,
    idempotency_key: str | None = None,
) -> int | None:
    """演练不消耗确认；真实资金回写必须消费本人绑定参数的一次性确认。"""
    if dry_run:
        return None
    try:
        if approval_id is None:
            approval = await create_self_approved_approval(
                session,
                tenant_id=tenant_id,
                action_type=action_type,
                payload=payload,
                operator_user_id=operator_user_id,
                confirmation=confirmation,
                idempotency_key=idempotency_key,
            )
            approval_id = approval.id
        approval = await claim_approval(
            session,
            approval_id=approval_id,
            tenant_id=tenant_id,
            action_type=action_type,
            payload=payload,
            operator_user_id=operator_user_id,
        )
        return approval.id
    except WritebackApprovalError as exc:
        raise WritebackError(str(exc)) from exc


async def _persist_funds_intent(
    session: AsyncSession,
    record: BidWriteback | WritebackAction,
    *,
    dry_run: bool,
) -> None:
    """真实写操作先持久化 pending 台账及可能存在的审批消费，再调用百度。

    这样即使外部调用后进程退出或最终状态提交失败，审批也不会回到可重复消费状态，
    pending 台账会明确要求人工对账。演练模式不需要拆分事务。
    """
    session.add(record)
    await session.flush()
    if not dry_run:
        await session.commit()


async def _persist_action_intent(
    session: AsyncSession,
    record: WritebackAction,
    *,
    dry_run: bool,
    asset: Any,
    account: BaiduAccount,
) -> None:
    """Persist a non-funds live intent, then reacquire the released locks."""
    await _persist_funds_intent(session, record, dry_run=dry_run)
    if not dry_run:
        await _relock_action_intent(session, record, asset=asset, account=account)


async def _relock_action_intent(
    session: AsyncSession,
    record: WritebackAction,
    *,
    asset: Any,
    account: BaiduAccount,
    related_records: list[WritebackAction] | None = None,
) -> None:
    records = [record, *(related_records or [])]
    await session.refresh(asset, with_for_update=True)
    await _relock_funds_account(
        session, account, record, related_records=related_records
    )
    if getattr(asset, "baidu_account_id", None) != account.id:
        for item in records:
            item.status = "failed"
            item.error_msg = "执行前复核失败：业务对象所属推广账户已变化"
            item.executed_at = datetime.utcnow()
        await session.commit()
        raise WritebackError("执行前复核失败：业务对象所属推广账户已变化")


async def _fail_action_preflight(
    session: AsyncSession,
    record: WritebackAction,
    message: str,
) -> None:
    record.status = "failed"
    record.error_msg = f"执行前复核失败：{message}"[:2000]
    record.executed_at = datetime.utcnow()
    await session.commit()
    raise WritebackError(record.error_msg)


async def _relock_funds_account(
    session: AsyncSession,
    account: BaiduAccount,
    record: BidWriteback | WritebackAction,
    related_records: list[WritebackAction] | None = None,
) -> None:
    """intent 提交后重新锁定并复核账户，避免停用账户继续真实回写。"""
    await session.refresh(account, with_for_update=True)
    records = [record, *(related_records or [])]
    # Reconciliation may finish in the commit→relock gap.  Lock and verify the
    # ledger before an account-state rejection writes anything, otherwise a
    # stale executor can overwrite a confirmed manual decision with ``failed``.
    for item in sorted(records, key=lambda value: int(value.id or 0)):
        await session.refresh(item, with_for_update=True)
        if item.status != "pending":
            raise WritebackError(
                f"回写台账 #{item.id} 已被处理为 {item.status}，本次不再调用百度"
            )
    if account.status == "active":
        return
    for item in records:
        item.status = "failed"
        item.error_msg = "执行前复核失败：推广账户授权已停用或归属状态已变化"
        item.executed_at = datetime.utcnow()
    await session.commit()
    raise WritebackError(record.error_msg)


async def _ensure_no_unresolved_funds_writeback(
    session: AsyncSession,
    model: Any,
    *conditions: Any,
) -> None:
    """同一对象存在未决真实写回时，禁止再次发起，避免重复执行。"""
    unresolved_id = await session.scalar(
        select(model.id).where(
            model.dry_run.is_(False),
            model.status.in_(UNRESOLVED_REAL_STATUSES),
            *conditions,
        ).with_for_update()
    )
    if unresolved_id is not None:
        raise WritebackError(
            f"该对象存在未完成或待人工对账的真实回写记录 #{unresolved_id}，请先完成对账再操作"
        )


def _record_writeback_exception(
    record: BidWriteback | WritebackAction,
    error: Exception,
    *,
    dry_run: bool,
) -> None:
    """网络或未知异常无法证明百度未执行；真实模式必须进入人工对账。"""
    definitive_api_failure = (
        isinstance(error, BaiduLiveWriteBlockedError)
        or (
            isinstance(error, BaiduAPIError)
            and not isinstance(error, BaiduHTTPError)
            and error.code is not None
        )
    )
    record.status = "failed" if dry_run or definitive_api_failure else "reconcile"
    if isinstance(error, BaiduAPIError):
        detail = f"[{error.code}] {error.message}"
    else:
        detail = str(error) or error.__class__.__name__
    prefix = "" if record.status == "failed" else "执行结果未知，需人工对账："
    record.error_msg = f"{prefix}{detail}"[:2000]
    record.executed_at = datetime.utcnow()


def _validate(old_bid: float | None, new_bid: float) -> float | None:
    """校验目标价，返回带方向的 change_pct（无旧价则 None）。"""
    if new_bid < MIN_BID or new_bid > MAX_BID:
        raise WritebackError(f"目标出价 {new_bid} 超出合法区间 [{MIN_BID}, {MAX_BID}]")
    if old_bid is None or old_bid <= 0:
        return None
    signed_change_pct = (new_bid - old_bid) / old_bid * 100
    if abs(signed_change_pct) > MAX_CHANGE_PCT + 1e-6:
        raise WritebackError(
            f"调价幅度 {abs(signed_change_pct):.1f}% 超过渐进调价硬上限 {MAX_CHANGE_PCT:.0f}%"
            f"（{old_bid} → {new_bid}）"
        )
    return round(signed_change_pct, 2)


async def apply_keyword_writeback(
    session: AsyncSession,
    tenant_id: int,
    keyword_id: int,
    new_bid: float,
    *,
    operator_user_id: int | None,
    operator_name: str | None,
    approval_id: int | None = None,
    confirmation: str | None = None,
    idempotency_key: str | None = None,
) -> BidWriteback:
    """把关键词的「最终执行价」回写百度，落台账并返回台账行。

    回写的是人工拍板的最终执行价（前端可在 AI 建议价基础上调整），不限于有 AI 建议的词。
    旧价快照 + 20% 硬上限基准 = 关键词库内当前出价（Keyword.price）。
    若该词当下有 pending 调价建议，关联其 id 并在真写成功后标记为已采纳。
    dry_run 开启时：走完校验、记台账（status=dry_run），但 client 拦截不真发百度。
    """
    kw = await session.scalar(
        select(Keyword).where(
            Keyword.tenant_id == tenant_id, Keyword.keyword_id == keyword_id
        ).with_for_update()
    )
    if kw is None:
        raise WritebackError("关键词不在维度表中，请先执行关键词维度同步")

    old_bid = float(kw.price) if kw.price is not None else None
    new_bid = round(float(new_bid), 2)
    change_pct = _validate(old_bid, new_bid)

    acc = await _active_account(session, tenant_id, _asset_account_id(kw, "关键词"))

    # 关联当下 pending 建议（可选）：用于记录来源 + 真写成功后标采纳
    sug = await session.scalar(
        select(Suggestion).where(
            Suggestion.tenant_id == tenant_id,
            Suggestion.keyword_id == keyword_id,
            Suggestion.status == "pending",
        ).with_for_update()
    )

    dry_run = await _effective_dry_run(
        session, tenant_id, acc, "keyword_bid", bid_change_pct=change_pct
    )
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session, BidWriteback,
            BidWriteback.tenant_id == tenant_id,
            BidWriteback.keyword_id == keyword_id,
        )
    effective_approval_id = await _claim_funds_approval(
        session,
        approval_id=approval_id,
        tenant_id=tenant_id,
        action_type=ACTION_KEYWORD_BID,
        payload={"keyword_id": keyword_id, "new_bid": new_bid},
        operator_user_id=operator_user_id,
        dry_run=dry_run,
        confirmation=confirmation,
        idempotency_key=idempotency_key,
    )

    rec = BidWriteback(
        tenant_id=tenant_id,
        baidu_account_id=acc.id,
        approval_id=effective_approval_id,
        suggestion_id=sug.id if sug else None,
        keyword_id=keyword_id,
        keyword=kw.keyword,
        campaign_id=kw.campaign_id,
        campaign_name=sug.campaign_name if sug else None,
        adgroup_id=kw.adgroup_id,
        old_bid=old_bid,
        new_bid=new_bid,
        change_pct=change_pct,
        dry_run=dry_run,
        status="pending",
        operator_user_id=operator_user_id,
        operator_name=operator_name,
    )
    await _persist_funds_intent(session, rec, dry_run=dry_run)
    if not dry_run:
        # intent 提交会释放原行锁；调用百度前重新加锁并按最新本地值复核。
        await session.refresh(kw, with_for_update=True)
        await _relock_funds_account(session, acc, rec)
        await session.refresh(rec, with_for_update=True)
        old_bid = float(kw.price) if kw.price is not None else None
        try:
            rec.change_pct = _validate(old_bid, new_bid)
            rec.old_bid = old_bid
        except WritebackError as exc:
            rec.status = "failed"
            rec.error_msg = f"执行前复核失败：{exc}"
            rec.executed_at = datetime.utcnow()
            await session.commit()
            raise

    try:
        svc = KeywordService(_account_client(acc))
        resp = await svc.update_word_bid(keyword_id, new_bid)
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
        # 真写成功才落地本地出价 + 标建议采纳；演练不改任何状态
        if not dry_run:
            kw.price = new_bid
            if sug:
                sug.status = "adopted"
                sug.adopted_at = datetime.utcnow()
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("回写失败 keyword_id=%s: %s", keyword_id, e)
    except Exception as e:  # 网络/未知错误也落台账，不静默
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("回写异常 keyword_id=%s", keyword_id)

    await session.commit()
    await session.refresh(rec)
    return rec


# ===== 加否词 / 转拓词（搜索词页发起，非出价类，记 writeback_actions） =====

# 匹配方式 → 百度 addWord (matchType, phraseType)（文档 0064/0068 核对）：
# 精确=1+1、短语=2+1、智能=2+3。两者必须配合传，否则百度按默认细分匹配处理。
_MATCH_BY_MODE = {"exact": (1, 1), "phrase": (2, 1), "smart": (2, 3)}
_VALID_MATCH_COMBOS = {
    (1, 1): "精确匹配",
    (2, 1): "短语匹配",
    (2, 3): "智能匹配",
}


async def _load_active_account(
    session: AsyncSession,
    tenant_id: int,
    baidu_account_id: int | None = None,
    *,
    lock: bool,
) -> BaiduAccount:
    conditions = [
        BaiduAccount.tenant_id == tenant_id,
        BaiduAccount.status == "active",
    ]
    if baidu_account_id is not None:
        conditions.append(BaiduAccount.id == baidu_account_id)
    query = select(BaiduAccount).where(*conditions).order_by(BaiduAccount.id)
    if lock:
        query = query.with_for_update()
    rows = list((await session.scalars(query)).all())
    if baidu_account_id is None and len(rows) > 1:
        raise WritebackError("当前客户有多个生效推广账户，必须明确选择要操作的账户")
    acc = rows[0] if rows else None
    if acc is None:
        if baidu_account_id is not None:
            raise WritebackError("计划所属的百度账户未授权或已停用，无法回写")
        raise WritebackError("该租户没有生效的百度账户授权，无法回写")
    return acc


async def _active_account(
    session: AsyncSession,
    tenant_id: int,
    baidu_account_id: int | None = None,
) -> BaiduAccount:
    """读取并锁定资金写回账户；普通写回不得绕过该锁。"""
    return await _load_active_account(
        session, tenant_id, baidu_account_id, lock=True
    )


async def _preflight_active_account(
    session: AsyncSession,
    tenant_id: int,
    baidu_account_id: int | None = None,
) -> BaiduAccount:
    """预算外部预读取专用快照；预读取结束后必须调用 `_active_account`。"""
    return await _load_active_account(
        session, tenant_id, baidu_account_id, lock=False
    )


def _asset_account_id(asset: Any, label: str) -> int:
    account_id = getattr(asset, "baidu_account_id", None)
    if account_id is None:
        raise WritebackError(f"{label}缺少所属百度账户，请先重新同步对应资产")
    return int(account_id)


async def _effective_dry_run(
    session: AsyncSession,
    tenant_id: int,
    account: BaiduAccount,
    write_scope: str,
    *,
    requested_attempts: int = 1,
    bid_change_pct: float | None = None,
) -> bool:
    """读取数据库策略，并向 HTTP 二次门禁传递本次动作能力。"""
    try:
        decision = await resolve_live_write_decision(
            session,
            get_settings(),
            tenant_id=tenant_id,
            account_id=account.id,
            write_scope=write_scope,
            requested_attempts=requested_attempts,
            bid_change_pct=bid_change_pct,
        )
    except SemLiveWritePolicyLimitError as exc:
        account._sem_live_write_authorized_scopes = frozenset()
        raise WritebackError(str(exc)) from exc
    account._sem_live_write_authorized_scopes = (
        frozenset() if decision.dry_run else frozenset({write_scope})
    )
    return decision.dry_run


async def apply_negative_writeback(
    session: AsyncSession,
    tenant_id: int,
    word: str,
    adgroup_id: int,
    *,
    match_mode: str,
    operator_user_id: int | None,
    operator_name: str | None,
) -> WritebackAction:
    """把搜索词加成单元否词（updateAdgroup 追加）。match_mode: exact=精确否 / phrase=短语否。

    百度否词全量覆盖：读本地单元当前否词 + 追加新词整体写回。dry_run 时拦截不真发。
    """
    word = (word or "").strip()
    if not word:
        raise WritebackError("否词不能为空")
    if match_mode not in ("exact", "phrase"):
        raise WritebackError("匹配方式只能是 exact（精确否）/ phrase（短语否）")

    adg = await session.scalar(
        select(Adgroup)
        .where(Adgroup.tenant_id == tenant_id, Adgroup.adgroup_id == adgroup_id)
        .with_for_update()
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    acc = await _active_account(session, tenant_id, _asset_account_id(adg, "单元"))

    field = "exact_negative_words" if match_mode == "exact" else "negative_words"
    current = list(getattr(adg, field) or [])
    if word in current:
        raise WritebackError(f"「{word}」已在该单元的{'精确' if match_mode == 'exact' else '短语'}否词中")
    new_list = current + [word]

    dry_run = await _effective_dry_run(session, tenant_id, acc, "adgroup_negative_words")
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session,
            WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.adgroup_id == adgroup_id,
            WritebackAction.match_mode == match_mode,
            WritebackAction.action_type.in_(("negative", "remove_negative")),
        )
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id, action_type="negative",
        word=word, match_mode=match_mode,
        campaign_id=adg.campaign_id, adgroup_id=adgroup_id, adgroup_name=adg.adgroup_name,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    await _persist_action_intent(
        session, rec, dry_run=dry_run, asset=adg, account=acc
    )
    if not dry_run:
        current = list(getattr(adg, field) or [])
        if word in current:
            await _fail_action_preflight(session, rec, "否词列表已变化，请核对后重试")
        new_list = current + [word]

    try:
        svc = AdgroupService(_account_client(acc))
        kwargs = (
            {"exact_negative_words": new_list}
            if match_mode == "exact"
            else {"negative_words": new_list}
        )
        resp = await svc.update_negative_words(adgroup_id, **kwargs)
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            setattr(adg, field, new_list)
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("加否词失败 adgroup=%s word=%s: %s", adgroup_id, word, e)
    except Exception as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("加否词异常 adgroup=%s word=%s", adgroup_id, word)

    await session.commit()
    await session.refresh(rec)
    return rec


async def apply_negative_batch_writeback(
    session: AsyncSession,
    tenant_id: int,
    words: list[str],
    adgroup_id: int,
    *,
    match_mode: str,
    operator_user_id: int | None,
    operator_name: str | None,
) -> list[NegativeBatchWritebackResult]:
    """一次更新单元的完整否词列表，并为每个请求词记录独立台账。

    百度 updateAdgroup 本身是全量覆盖接口；批量操作必须在同一把行锁内
    合并词表后只调用一次，避免浏览器超时后服务端继续串行写入。
    真实模式会在调用百度前提交 pending 台账；候选词状态仍由 API 另行提交。
    """
    normalized_words = [(word or "").strip() for word in words]
    if not normalized_words or any(not word for word in normalized_words):
        raise WritebackError("否词不能为空")
    if match_mode not in ("exact", "phrase"):
        raise WritebackError("匹配方式只能是 exact（精确否）/ phrase（短语否）")

    adg = await session.scalar(
        select(Adgroup)
        .where(Adgroup.tenant_id == tenant_id, Adgroup.adgroup_id == adgroup_id)
        .with_for_update()
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    acc = await _active_account(session, tenant_id, _asset_account_id(adg, "单元"))

    field = "exact_negative_words" if match_mode == "exact" else "negative_words"
    current = list(getattr(adg, field) or [])
    current_words = set(current)
    new_words: list[str] = []
    requested_attempts = len({word for word in normalized_words if word not in current_words})
    dry_run = await _effective_dry_run(
        session,
        tenant_id,
        acc,
        "adgroup_negative_words",
        requested_attempts=requested_attempts,
    )
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session,
            WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.adgroup_id == adgroup_id,
            WritebackAction.match_mode == match_mode,
            WritebackAction.action_type.in_(("negative", "remove_negative")),
        )
    results: list[NegativeBatchWritebackResult] = []
    results_by_word: dict[str, NegativeBatchWritebackResult] = {}
    pending_results: list[NegativeBatchWritebackResult] = []

    for word in normalized_words:
        existing_result = results_by_word.get(word)
        if existing_result is not None:
            results.append(existing_result)
            continue
        if word in current_words:
            result = NegativeBatchWritebackResult(
                word=word,
                status="success",
                no_op=True,
            )
            results_by_word[word] = result
            results.append(result)
            continue

        rec = WritebackAction(
            tenant_id=tenant_id,
            baidu_account_id=acc.id,
            action_type="negative",
            word=word,
            match_mode=match_mode,
            campaign_id=adg.campaign_id,
            adgroup_id=adgroup_id,
            adgroup_name=adg.adgroup_name,
            dry_run=dry_run,
            status="pending",
            operator_user_id=operator_user_id,
            operator_name=operator_name,
        )
        session.add(rec)
        new_words.append(word)
        result = NegativeBatchWritebackResult(
            word=word,
            status="pending",
            record=rec,
        )
        results_by_word[word] = result
        pending_results.append(result)
        results.append(result)

    await session.flush()
    if pending_results:
        if not dry_run:
            await session.commit()
            first_record = pending_results[0].record
            assert first_record is not None
            await _relock_action_intent(
                session,
                first_record,
                asset=adg,
                account=acc,
                related_records=[
                    result.record
                    for result in pending_results[1:]
                    if result.record is not None
                ],
            )
            current = list(getattr(adg, field) or [])
            if any(word in current for word in new_words):
                for result in pending_results:
                    result.record.status = "failed"
                    result.record.error_msg = "执行前复核失败：否词列表已变化，请核对后重试"
                    result.record.executed_at = datetime.utcnow()
                await session.commit()
                raise WritebackError("执行前复核失败：否词列表已变化，请核对后重试")
        try:
            kwargs = (
                {"exact_negative_words": current + new_words}
                if match_mode == "exact"
                else {"negative_words": current + new_words}
            )
            resp = await AdgroupService(_account_client(acc)).update_negative_words(
                adgroup_id, **kwargs
            )
            status = "dry_run" if dry_run else "success"
            executed_at = datetime.utcnow()
            response_text = str(resp)[:2000]
            for result in pending_results:
                rec = result.record
                assert rec is not None
                rec.status = status
                rec.baidu_response = response_text
                rec.executed_at = executed_at
                result.status = status
            if not dry_run:
                setattr(adg, field, current + new_words)
        except BaiduAPIError as exc:
            for result in pending_results:
                rec = result.record
                assert rec is not None
                _record_writeback_exception(rec, exc, dry_run=dry_run)
                result.status = rec.status
                result.error_msg = rec.error_msg
            logger.warning(
                "批量加否词失败 adgroup=%s count=%s: %s",
                adgroup_id,
                len(pending_results),
                exc,
            )
        except Exception as exc:
            for result in pending_results:
                rec = result.record
                assert rec is not None
                _record_writeback_exception(rec, exc, dry_run=dry_run)
                result.status = rec.status
                result.error_msg = rec.error_msg
            logger.exception(
                "批量加否词异常 adgroup=%s count=%s",
                adgroup_id,
                len(pending_results),
            )
        if not dry_run:
            await session.commit()

    return results


async def apply_negative_writeback_campaign(
    session: AsyncSession,
    tenant_id: int,
    word: str,
    campaign_id: int,
    *,
    match_mode: str,
    operator_user_id: int | None,
    operator_name: str | None,
) -> WritebackAction:
    """把搜索词加成计划级否词。match_mode: exact=精确否 / phrase=短语否。"""
    word = (word or "").strip()
    if not word:
        raise WritebackError("否词不能为空")
    if match_mode not in ("exact", "phrase"):
        raise WritebackError("匹配方式只能是 exact（精确否）/ phrase（短语否）")

    camp = await session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == tenant_id,
            Campaign.campaign_id == campaign_id,
        ).with_for_update()
    )
    if camp is None:
        raise WritebackError("计划不在维度表中，请先执行计划维度同步")
    acc = await _active_account(session, tenant_id, _asset_account_id(camp, "计划"))

    field = "exact_negative_words" if match_mode == "exact" else "negative_words"
    current = list(getattr(camp, field) or [])
    if word in current:
        raise WritebackError(
            f"「{word}」已在该计划的{'精确' if match_mode == 'exact' else '短语'}否词中"
        )
    new_list = current + [word]

    dry_run = await _effective_dry_run(session, tenant_id, acc, "campaign_negative_words")
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session,
            WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.campaign_id == campaign_id,
            WritebackAction.adgroup_id.is_(None),
            WritebackAction.match_mode == match_mode,
            WritebackAction.action_type.in_(("negative", "remove_negative")),
        )
    rec = WritebackAction(
        tenant_id=tenant_id,
        baidu_account_id=acc.id,
        action_type="negative",
        word=word,
        match_mode=match_mode,
        campaign_id=campaign_id,
        campaign_name=camp.campaign_name,
        dry_run=dry_run,
        status="pending",
        operator_user_id=operator_user_id,
        operator_name=operator_name,
    )
    await _persist_action_intent(
        session, rec, dry_run=dry_run, asset=camp, account=acc
    )
    if not dry_run:
        current = list(getattr(camp, field) or [])
        if word in current:
            await _fail_action_preflight(session, rec, "否词列表已变化，请核对后重试")
        new_list = current + [word]

    try:
        kwargs = (
            {"exact_negative_words": new_list}
            if match_mode == "exact"
            else {"negative_words": new_list}
        )
        resp = await CampaignService(_account_client(acc)).update_campaign_negative_words(
            campaign_id,
            **kwargs,
        )
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            setattr(camp, field, new_list)
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("计划级加否词失败 campaign=%s word=%s: %s", campaign_id, word, e)
    except Exception as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("计划级加否词异常 campaign=%s word=%s", campaign_id, word)

    await session.commit()
    await session.refresh(rec)
    return rec


async def apply_add_word_writeback(
    session: AsyncSession,
    tenant_id: int,
    word: str,
    adgroup_id: int,
    *,
    price: float,
    match_mode: str,
    operator_user_id: int | None,
    operator_name: str | None,
) -> WritebackAction:
    """把搜索词加成正式关键词（addWord）到指定单元。match_mode: exact/phrase/smart。

    出价受合法区间校验。dry_run 时拦截不真发。
    """
    word = (word or "").strip()
    if not word:
        raise WritebackError("关键词不能为空")
    if match_mode not in _MATCH_BY_MODE:
        raise WritebackError("匹配方式只能是 exact / phrase / smart")
    price = round(float(price), 2)
    if not math.isfinite(price):
        raise WritebackError("出价必须是有限数值")
    if price < MIN_BID or price > MAX_BID:
        raise WritebackError(f"出价 {price} 超出合法区间 [{MIN_BID}, {MAX_BID}]")

    adg = await session.scalar(
        select(Adgroup).where(Adgroup.tenant_id == tenant_id, Adgroup.adgroup_id == adgroup_id).with_for_update()
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    acc = await _active_account(session, tenant_id, _asset_account_id(adg, "单元"))
    dry_run = await _effective_dry_run(session, tenant_id, acc, "keyword_create")
    await _ensure_add_word_not_duplicate(
        session,
        tenant_id=tenant_id,
        adgroup_id=adgroup_id,
        word=word,
        dry_run=dry_run,
    )

    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id, action_type="add_word",
        word=word, match_mode=match_mode, price=price,
        campaign_id=adg.campaign_id, adgroup_id=adgroup_id, adgroup_name=adg.adgroup_name,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    await _persist_action_intent(
        session, rec, dry_run=dry_run, asset=adg, account=acc
    )
    if not dry_run:
        try:
            await _ensure_add_word_not_duplicate(
                session,
                tenant_id=tenant_id,
                adgroup_id=adgroup_id,
                word=word,
                dry_run=dry_run,
                exclude_record_id=rec.id,
            )
        except WritebackError as exc:
            await _fail_action_preflight(session, rec, str(exc))

    try:
        svc = KeywordService(_account_client(acc))
        match_type, phrase_type = _MATCH_BY_MODE[match_mode]
        resp = await svc.add_word(adgroup_id, word, match_type, phrase_type, price)
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("转拓词失败 adgroup=%s word=%s: %s", adgroup_id, word, e)
    except Exception as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("转拓词异常 adgroup=%s word=%s", adgroup_id, word)

    await session.commit()
    await session.refresh(rec)
    return rec


async def apply_pause_writeback(
    session: AsyncSession,
    tenant_id: int,
    keyword_id: int,
    pause: bool,
    *,
    operator_user_id: int | None,
    operator_name: str | None,
) -> WritebackAction:
    """暂停 / 启用关键词（updateWord pause）。dry_run 时拦截不真发。真写成功落地本地 pause。"""
    kw = await session.scalar(
        select(Keyword).where(Keyword.tenant_id == tenant_id, Keyword.keyword_id == keyword_id).with_for_update()
    )
    if kw is None:
        raise WritebackError("关键词不在维度表中，请先执行关键词维度同步")
    acc = await _active_account(session, tenant_id, _asset_account_id(kw, "关键词"))
    old_pause = kw.pause
    dry_run = await _effective_dry_run(session, tenant_id, acc, "keyword_pause")
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session,
            WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.baidu_account_id == acc.id,
            WritebackAction.word == kw.keyword,
            WritebackAction.adgroup_id == kw.adgroup_id,
            WritebackAction.action_type.in_(("pause", "enable")),
        )
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id,
        action_type="pause" if pause else "enable",
        word=kw.keyword, campaign_id=kw.campaign_id, adgroup_id=kw.adgroup_id,
        old_value=_boolean_audit_value(old_pause), new_value=int(pause),
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    await _persist_action_intent(
        session, rec, dry_run=dry_run, asset=kw, account=acc
    )
    if not dry_run and kw.pause != old_pause:
        await _fail_action_preflight(session, rec, "关键词启停状态已变化，请核对后重试")
    try:
        svc = KeywordService(_account_client(acc))
        resp = await svc.update_word_pause(keyword_id, pause)
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            kw.pause = pause
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("启停失败 keyword_id=%s pause=%s: %s", keyword_id, pause, e)
    except Exception as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("启停异常 keyword_id=%s", keyword_id)

    await session.commit()
    await session.refresh(rec)
    return rec


async def apply_match_type_writeback(
    session: AsyncSession,
    tenant_id: int,
    keyword_id: int,
    match_type: int,
    phrase_type: int,
    *,
    operator_user_id: int | None,
    operator_name: str | None,
) -> WritebackAction:
    """修改关键词匹配模式（updateWord matchType/phraseType）。dry_run 时拦截不真发。"""
    combo = (match_type, phrase_type)
    if combo not in _VALID_MATCH_COMBOS:
        raise WritebackError(
            f"不支持的匹配模式组合 matchType={match_type}, phraseType={phrase_type}，"
            f"仅支持精确(1,1) / 短语(2,1) / 智能(2,3)"
        )

    kw = await session.scalar(
        select(Keyword).where(
            Keyword.tenant_id == tenant_id,
            Keyword.keyword_id == keyword_id,
        ).with_for_update()
    )
    if kw is None:
        raise WritebackError("关键词不在维度表中，请先执行关键词维度同步")
    acc = await _active_account(session, tenant_id, _asset_account_id(kw, "关键词"))
    old_match_combo = (kw.match_type, kw.phrase_type)

    dry_run = await _effective_dry_run(session, tenant_id, acc, "keyword_match_type")
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session,
            WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.baidu_account_id == acc.id,
            WritebackAction.word == kw.keyword,
            WritebackAction.adgroup_id == kw.adgroup_id,
            WritebackAction.action_type == "set_match_type",
        )
    match_audit = {
        "schema": "sem.match_change",
        "version": 1,
        "old": {"matchType": old_match_combo[0], "phraseType": old_match_combo[1]},
        "new": {"matchType": match_type, "phraseType": phrase_type},
    }
    rec = WritebackAction(
        tenant_id=tenant_id,
        baidu_account_id=acc.id,
        action_type="set_match_type",
        word=kw.keyword,
        match_mode=_VALID_MATCH_COMBOS[combo],
        campaign_id=kw.campaign_id,
        adgroup_id=kw.adgroup_id,
        old_value=kw.match_type,
        new_value=match_type,
        baidu_response=json.dumps(match_audit, ensure_ascii=False, default=str),
        dry_run=dry_run,
        status="pending",
        operator_user_id=operator_user_id,
        operator_name=operator_name,
    )
    await _persist_action_intent(
        session, rec, dry_run=dry_run, asset=kw, account=acc
    )
    if not dry_run and (kw.match_type, kw.phrase_type) != old_match_combo:
        await _fail_action_preflight(session, rec, "关键词匹配模式已变化，请核对后重试")
    try:
        svc = KeywordService(_account_client(acc))
        resp = await svc.update_word_match_type(keyword_id, match_type, phrase_type)
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = json.dumps(
            {**match_audit, "baidu": _bounded_response_summary(resp)},
            ensure_ascii=False,
            default=str,
        )
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            kw.match_type = match_type
            kw.phrase_type = phrase_type
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("改匹配模式失败 keyword_id=%s: %s", keyword_id, e)
    except Exception as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("改匹配模式异常 keyword_id=%s", keyword_id)

    await session.commit()
    await session.refresh(rec)
    return rec


async def apply_remove_negative_writeback(
    session: AsyncSession,
    tenant_id: int,
    word: str,
    adgroup_id: int,
    *,
    match_mode: str,
    operator_user_id: int | None,
    operator_name: str | None,
) -> WritebackAction:
    """从单元否词中删除一个词（updateAdgroup 全量覆盖：读当前否词 - 移除）。dry_run 拦截。"""
    word = (word or "").strip()
    if match_mode not in ("exact", "phrase"):
        raise WritebackError("匹配方式只能是 exact / phrase")
    adg = await session.scalar(
        select(Adgroup).where(Adgroup.tenant_id == tenant_id, Adgroup.adgroup_id == adgroup_id).with_for_update()
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    acc = await _active_account(session, tenant_id, _asset_account_id(adg, "单元"))

    field = "exact_negative_words" if match_mode == "exact" else "negative_words"
    current = list(getattr(adg, field) or [])
    if word not in current:
        raise WritebackError(f"「{word}」不在该单元的{'精确' if match_mode == 'exact' else '短语'}否词中")
    new_list = [w for w in current if w != word]

    dry_run = await _effective_dry_run(session, tenant_id, acc, "adgroup_negative_words")
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session,
            WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.adgroup_id == adgroup_id,
            WritebackAction.match_mode == match_mode,
            WritebackAction.action_type.in_(("negative", "remove_negative")),
        )
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id, action_type="remove_negative",
        word=word, match_mode=match_mode,
        campaign_id=adg.campaign_id, adgroup_id=adgroup_id, adgroup_name=adg.adgroup_name,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    await _persist_action_intent(
        session, rec, dry_run=dry_run, asset=adg, account=acc
    )
    if not dry_run:
        current = list(getattr(adg, field) or [])
        if word not in current:
            await _fail_action_preflight(session, rec, "否词列表已变化，请核对后重试")
        new_list = [item for item in current if item != word]
    try:
        svc = AdgroupService(_account_client(acc))
        kwargs = (
            {"exact_negative_words": new_list}
            if match_mode == "exact"
            else {"negative_words": new_list}
        )
        resp = await svc.update_negative_words(adgroup_id, **kwargs)
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            setattr(adg, field, new_list)
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("删否词失败 adgroup=%s word=%s: %s", adgroup_id, word, e)
    except Exception as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("删否词异常 adgroup=%s word=%s", adgroup_id, word)

    await session.commit()
    await session.refresh(rec)
    return rec


async def apply_campaign_budget_writeback(
    session: AsyncSession,
    tenant_id: int,
    campaign_id: int,
    new_budget: float,
    *,
    operator_user_id: int | None,
    operator_name: str | None,
    approval_id: int | None = None,
    confirmation: str | None = None,
    idempotency_key: str | None = None,
) -> WritebackAction:
    """计划日预算写回（updateCampaign budget，文档 0046）。dry_run 时拦截不真发。

    旧预算取本地 campaigns 表快照。校验 [50, min(1e7, 账户预算)]——计划预算不能超账户预算
    （提前拦比百度报错友好；账户预算实时查，查不到则放过交百度兜底）。真写成功落地本地 budget。
    """
    new_budget = round(float(new_budget), 2)
    if new_budget < MIN_ACCOUNT_BUDGET or new_budget > MAX_ACCOUNT_BUDGET:
        raise WritebackError(
            f"计划日预算 {new_budget} 超出合法区间 "
            f"[{MIN_ACCOUNT_BUDGET:.0f}, {MAX_ACCOUNT_BUDGET:.0f}]"
        )
    campaign_query = select(Campaign).where(
        Campaign.tenant_id == tenant_id, Campaign.campaign_id == campaign_id
    )
    camp = await session.scalar(campaign_query)
    if camp is None:
        raise WritebackError("计划不在维度表中，请先执行计划维度同步")
    acc = await _preflight_active_account(
        session,
        tenant_id,
        _asset_account_id(camp, "计划"),
    )
    preflight_account_id = acc.id

    # 计划预算不能超账户日预算：实时查账户预算做上限校验（失败不阻断，交百度兜底）
    try:
        info = (await AccountService(_account_client(acc)).get_account_info(
            ["budget", "budgetType"]
        )).get("data") or {}
        if isinstance(info, list):
            info = info[0] if info else {}
        acct_budget = info.get("budget")
        if acct_budget is not None and float(acct_budget) > 0 and new_budget > float(acct_budget):
            raise WritebackError(
                f"计划日预算 {new_budget} 不能超过账户日预算 {float(acct_budget):.2f}"
            )
    except WritebackError:
        raise
    except Exception:  # noqa: BLE001  查账户预算失败不挡写回
        logger.warning("计划预算写回：查账户预算失败，跳过上限预校验", exc_info=True)

    # 外部预读取完成后再进入资金操作的串行化区间，避免百度接口慢时长期
    # 占用计划/账户行锁。加锁后重新读取并复核归属，防止预读取期间资产变化。
    camp = await session.scalar(
        campaign_query.execution_options(populate_existing=True).with_for_update()
    )
    if camp is None:
        raise WritebackError("计划不在维度表中，请先执行计划维度同步")
    locked_account_id = _asset_account_id(camp, "计划")
    if locked_account_id != preflight_account_id:
        raise WritebackError("计划所属推广账户已变化，请重试")
    acc = await _active_account(session, tenant_id, locked_account_id)

    old_budget = float(camp.budget) if camp.budget is not None else None
    dry_run = await _effective_dry_run(session, tenant_id, acc, "campaign_budget")
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session, WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.action_type == "set_campaign_budget",
            WritebackAction.campaign_id == campaign_id,
        )
    effective_approval_id = await _claim_funds_approval(
        session,
        approval_id=approval_id,
        tenant_id=tenant_id,
        action_type=ACTION_CAMPAIGN_BUDGET,
        payload={"campaign_id": campaign_id, "new_budget": new_budget},
        operator_user_id=operator_user_id,
        dry_run=dry_run,
        confirmation=confirmation,
        idempotency_key=idempotency_key,
    )
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id, action_type="set_campaign_budget",
        approval_id=effective_approval_id,
        word=camp.campaign_name or f"计划#{campaign_id}",
        campaign_id=campaign_id, campaign_name=camp.campaign_name,
        old_value=old_budget, new_value=new_budget,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    await _persist_funds_intent(session, rec, dry_run=dry_run)
    if not dry_run:
        await session.refresh(camp, with_for_update=True)
        await _relock_funds_account(session, acc, rec)
        await session.refresh(rec, with_for_update=True)
        rec.old_value = float(camp.budget) if camp.budget is not None else None
    try:
        resp = await CampaignService(_account_client(acc)).update_campaign_budget(
            campaign_id, new_budget
        )
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            camp.budget = new_budget
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("计划预算写回失败 campaign=%s budget=%s: %s", campaign_id, new_budget, e)
    except Exception as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("计划预算写回异常 campaign=%s", campaign_id)

    await session.commit()
    await session.refresh(rec)
    return rec


# ===== 计划 / 单元启停 + 单元出价（投放管理） =====


async def apply_campaign_pause_writeback(
    session: AsyncSession,
    tenant_id: int,
    campaign_id: int,
    pause: bool,
    *,
    operator_user_id: int | None,
    operator_name: str | None,
) -> WritebackAction:
    """计划启停（updateCampaign pause）。dry_run 拦截不真发，真写成功落地本地 pause。"""
    camp = await session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == tenant_id, Campaign.campaign_id == campaign_id
        ).with_for_update()
    )
    if camp is None:
        raise WritebackError("计划不在维度表中，请先执行计划维度同步")
    acc = await _active_account(session, tenant_id, _asset_account_id(camp, "计划"))
    old_pause = camp.pause

    dry_run = await _effective_dry_run(session, tenant_id, acc, "campaign_pause")
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session,
            WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.campaign_id == campaign_id,
            WritebackAction.action_type.in_(CAMPAIGN_PAUSE_CONFLICT_ACTIONS),
        )
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id,
        action_type="campaign_pause" if pause else "campaign_enable",
        word=camp.campaign_name or f"计划#{campaign_id}",
        campaign_id=campaign_id, campaign_name=camp.campaign_name,
        old_value=_boolean_audit_value(old_pause), new_value=int(pause),
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    await _persist_action_intent(
        session, rec, dry_run=dry_run, asset=camp, account=acc
    )
    if not dry_run and camp.pause != old_pause:
        await _fail_action_preflight(session, rec, "计划启停状态已变化，请核对后重试")
    try:
        resp = await CampaignService(_account_client(acc)).update_campaign_pause(
            campaign_id, pause
        )
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            camp.pause = pause
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("计划启停失败 campaign=%s pause=%s: %s", campaign_id, pause, e)
    except Exception as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("计划启停异常 campaign=%s", campaign_id)

    await session.commit()
    await session.refresh(rec)
    return rec


def _normalize_schedule_price_factors(items: list[dict]) -> list[dict[str, float | int]]:
    """校验并规范百度 timeId（星期 * 100 + 小时）的完整投放时段。"""
    if not isinstance(items, list):
        raise WritebackError("投放时段必须是列表")
    normalized: list[dict[str, float | int]] = []
    seen: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            raise WritebackError("投放时段格式错误")
        time_id = item.get("timeId")
        factor = item.get("priceFactor", 1)
        if isinstance(time_id, bool) or not isinstance(time_id, int):
            raise WritebackError("投放时段 timeId 必须是整数")
        week_day, hour = divmod(time_id, 100)
        if not 1 <= week_day <= 7 or not 0 <= hour <= 23:
            raise WritebackError("投放时段必须是周一至周日的整点时段")
        try:
            normalized_factor = float(factor)
        except (TypeError, ValueError) as exc:
            raise WritebackError("分时段出价系数必须是数字") from exc
        if not 0.1 <= normalized_factor <= 10.0:
            raise WritebackError("分时段出价系数必须在 0.1 到 10.0 之间")
        if time_id in seen:
            raise WritebackError("同一投放时段不能重复设置")
        seen.add(time_id)
        normalized.append({"timeId": time_id, "priceFactor": normalized_factor})
    return sorted(normalized, key=lambda row: int(row["timeId"]))


async def apply_campaign_schedule_writeback(
    session: AsyncSession,
    tenant_id: int,
    campaign_id: int,
    schedule_price_factors: list[dict],
    *,
    pause: bool = False,
    operator_user_id: int | None,
    operator_name: str | None,
) -> WritebackAction:
    """写回计划投放时段；空时段只允许用于节假日停投模板。"""
    normalized = _normalize_schedule_price_factors(schedule_price_factors)
    if not normalized and not pause:
        raise WritebackError("投放时段不能为空；如需节假日停投请选择停投模板")
    camp = await session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == tenant_id, Campaign.campaign_id == campaign_id
        ).with_for_update()
    )
    if camp is None:
        raise WritebackError("计划不在维度表中，请先执行计划维度同步")
    if camp.baidu_account_id is None:
        raise WritebackError("计划缺少所属百度账户，请先重新同步计划维度")
    acc = await _active_account(session, tenant_id, camp.baidu_account_id)
    old_schedule = list(camp.schedule_price_factors or [])
    old_pause = bool(camp.pause)
    dry_run = await _effective_dry_run(session, tenant_id, acc, "campaign_schedule")
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session,
            WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.campaign_id == campaign_id,
            WritebackAction.action_type.in_(CAMPAIGN_PAUSE_CONFLICT_ACTIONS),
        )
    rec = WritebackAction(
        tenant_id=tenant_id,
        baidu_account_id=acc.id,
        action_type="campaign_schedule",
        word=camp.campaign_name or f"计划#{campaign_id}",
        campaign_id=campaign_id,
        campaign_name=camp.campaign_name,
        old_value=len(old_schedule),
        new_value=len(normalized),
        dry_run=dry_run,
        status="pending",
        operator_user_id=operator_user_id,
        operator_name=operator_name,
    )
    await _persist_action_intent(
        session, rec, dry_run=dry_run, asset=camp, account=acc
    )
    if not dry_run and (
        list(camp.schedule_price_factors or []) != old_schedule
        or bool(camp.pause) != old_pause
    ):
        await _fail_action_preflight(session, rec, "计划时段或启停状态已变化，请核对后重试")
    try:
        resp = await CampaignService(_account_client(acc)).update_campaign_schedule(
            campaign_id, normalized, pause=pause
        )
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            camp.schedule_price_factors = normalized
            if pause:
                camp.pause = True
    except BaiduAPIError as exc:
        _record_writeback_exception(rec, exc, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        _record_writeback_exception(rec, exc, dry_run=dry_run)
        logger.exception("投放时段写回异常 campaign=%s", campaign_id)
    await session.commit()
    await session.refresh(rec)
    return rec


def _normalize_region_target(region_target: list[int]) -> list[int]:
    if not isinstance(region_target, list) or not region_target:
        raise WritebackError("投放地域不能为空，请至少选择一个省、市或全部区域")
    normalized: list[int] = []
    allowed_ids = region_ids()
    for region_id in region_target:
        if isinstance(region_id, bool) or not isinstance(region_id, int) or region_id <= 0:
            raise WritebackError("投放地域必须是有效的百度地域 ID")
        if region_id not in allowed_ids:
            raise WritebackError(f"地域 ID {region_id} 不在当前百度地域编码表中")
        if region_id not in normalized:
            normalized.append(region_id)
    if ALL_REGIONS_ID in normalized and len(normalized) > 1:
        raise WritebackError("“全部区域”不能与其他省市同时选择")
    return normalized


def _normalize_region_price_factor(
    region_price_factor: list[dict] | None, region_target: list[int]
) -> list[dict[str, float | int]] | None:
    if region_price_factor is None:
        return None
    if not isinstance(region_price_factor, list):
        raise WritebackError("分地域出价系数必须是列表")

    normalized: list[dict[str, float | int]] = []
    seen: set[int] = set()
    for item in region_price_factor:
        if not isinstance(item, dict):
            raise WritebackError("分地域出价系数格式错误")
        region_id = item.get("regionId")
        factor = item.get("priceFactor")
        if isinstance(region_id, bool) or not isinstance(region_id, int) or region_id not in region_target:
            raise WritebackError("分地域出价系数的地域必须在投放地域列表中")
        if isinstance(factor, bool):
            raise WritebackError("分地域出价系数必须是数字")
        try:
            normalized_factor = float(factor)
        except (TypeError, ValueError) as exc:
            raise WritebackError("分地域出价系数必须是数字") from exc
        if not 0.1 <= normalized_factor <= 1.0:
            raise WritebackError("分地域出价系数必须在 0.1 到 1.0 之间")
        if region_id in seen:
            raise WritebackError("同一地域只能设置一个出价系数")
        seen.add(region_id)
        normalized.append({"regionId": region_id, "priceFactor": normalized_factor})
    return normalized


async def apply_campaign_region_writeback(
    session: AsyncSession,
    tenant_id: int,
    campaign_id: int,
    region_target: list[int],
    region_price_factor: list[dict] | None,
    geo_location_status: int | None = None,
    *,
    operator_user_id: int | None,
    operator_name: str | None,
) -> WritebackAction:
    """更新计划投放地域、分地域系数及地域定向方式；dry-run 时仅写入台账。"""
    normalized_regions = _normalize_region_target(region_target)
    normalized_factors = _normalize_region_price_factor(region_price_factor, normalized_regions)
    if geo_location_status is not None and geo_location_status not in (0, 1):
        raise WritebackError("地域定向方式只能是 0（含搜索意图）或 1（仅地区内用户）")
    camp = await session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == tenant_id, Campaign.campaign_id == campaign_id
        ).with_for_update()
    )
    if camp is None:
        raise WritebackError("计划不在维度表中，请先执行计划维度同步")
    if camp.baidu_account_id is None:
        raise WritebackError("计划缺少所属百度账户，请先重新同步计划维度")
    acc = await _active_account(session, tenant_id, camp.baidu_account_id)

    old_regions = list(camp.region_target or [])
    old_region_factors = list(camp.region_price_factor or [])
    old_geo_location_status = camp.geo_location_status
    dry_run = await _effective_dry_run(session, tenant_id, acc, "campaign_region")
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session,
            WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.campaign_id == campaign_id,
            WritebackAction.action_type == "set_campaign_region",
        )
    rec = WritebackAction(
        tenant_id=tenant_id,
        baidu_account_id=acc.id,
        action_type="set_campaign_region",
        word=camp.campaign_name or f"计划#{campaign_id}",
        campaign_id=campaign_id,
        campaign_name=camp.campaign_name,
        old_value=len(old_regions),
        new_value=len(normalized_regions),
        dry_run=dry_run,
        status="pending",
        operator_user_id=operator_user_id,
        operator_name=operator_name,
    )
    await _persist_action_intent(
        session, rec, dry_run=dry_run, asset=camp, account=acc
    )
    if not dry_run and (
        list(camp.region_target or []) != old_regions
        or list(camp.region_price_factor or []) != old_region_factors
        or camp.geo_location_status != old_geo_location_status
    ):
        await _fail_action_preflight(session, rec, "计划地域设置已变化，请核对后重试")

    try:
        resp = await CampaignService(_account_client(acc)).update_campaign_region(
            campaign_id,
            normalized_regions,
            region_price_factor=normalized_factors,
            geo_location_status=geo_location_status,
        )
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            camp.region_target = normalized_regions
            if normalized_factors is not None:
                camp.region_price_factor = normalized_factors
            if geo_location_status is not None:
                camp.geo_location_status = geo_location_status
    except BaiduAPIError as exc:
        _record_writeback_exception(rec, exc, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        _record_writeback_exception(rec, exc, dry_run=dry_run)
        logger.exception("地域写回异常 campaign=%s", campaign_id)

    await session.commit()
    await session.refresh(rec)
    return rec


async def apply_adgroup_pause_writeback(
    session: AsyncSession,
    tenant_id: int,
    adgroup_id: int,
    pause: bool,
    *,
    operator_user_id: int | None,
    operator_name: str | None,
) -> WritebackAction:
    """单元启停（updateAdgroup pause）。dry_run 拦截，真写成功落地本地 pause。"""
    adg = await session.scalar(
        select(Adgroup).where(
            Adgroup.tenant_id == tenant_id, Adgroup.adgroup_id == adgroup_id
        ).with_for_update()
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    acc = await _active_account(session, tenant_id, _asset_account_id(adg, "单元"))
    old_pause = adg.pause

    dry_run = await _effective_dry_run(session, tenant_id, acc, "adgroup_pause")
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session,
            WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.adgroup_id == adgroup_id,
            WritebackAction.action_type.in_(("adgroup_pause", "adgroup_enable")),
        )
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id,
        action_type="adgroup_pause" if pause else "adgroup_enable",
        word=adg.adgroup_name or f"单元#{adgroup_id}",
        campaign_id=adg.campaign_id, adgroup_id=adgroup_id, adgroup_name=adg.adgroup_name,
        old_value=_boolean_audit_value(old_pause), new_value=int(pause),
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    await _persist_action_intent(
        session, rec, dry_run=dry_run, asset=adg, account=acc
    )
    if not dry_run and adg.pause != old_pause:
        await _fail_action_preflight(session, rec, "单元启停状态已变化，请核对后重试")
    try:
        resp = await AdgroupService(_account_client(acc)).update_adgroup_fields(
            adgroup_id, pause=pause
        )
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            adg.pause = pause
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("单元启停失败 adgroup=%s pause=%s: %s", adgroup_id, pause, e)
    except Exception as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("单元启停异常 adgroup=%s", adgroup_id)

    await session.commit()
    await session.refresh(rec)
    return rec


async def apply_adgroup_bid_writeback(
    session: AsyncSession,
    tenant_id: int,
    adgroup_id: int,
    new_price: float,
    *,
    operator_user_id: int | None,
    operator_name: str | None,
    approval_id: int | None = None,
    confirmation: str | None = None,
    idempotency_key: str | None = None,
) -> WritebackAction:
    """单元出价 maxPrice 写回（updateAdgroup）。校验 (0,999.99] 且 ≤ 所属计划预算。

    旧价取本地 adgroups 表快照。dry_run 拦截，真写成功落地本地 max_price。
    """
    new_price = round(float(new_price), 2)
    if new_price < MIN_BID or new_price > MAX_BID:
        raise WritebackError(f"单元出价 {new_price} 超出合法区间 ({MIN_BID}, {MAX_BID}]")
    adg = await session.scalar(
        select(Adgroup).where(
            Adgroup.tenant_id == tenant_id, Adgroup.adgroup_id == adgroup_id
        ).with_for_update()
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    # 单元出价不能超所属计划预算（本地有预算时预校验）
    camp = None
    if adg.campaign_id is not None:
        camp = await session.scalar(
            select(Campaign).where(
                Campaign.tenant_id == tenant_id, Campaign.campaign_id == adg.campaign_id
            ).with_for_update()
        )
        if camp is not None and camp.budget is not None and new_price > float(camp.budget):
            raise WritebackError(
                f"单元出价 {new_price} 不能超过所属计划日预算 {float(camp.budget):.2f}"
            )
    acc = await _active_account(session, tenant_id, _asset_account_id(adg, "单元"))

    old_price = float(adg.max_price) if adg.max_price is not None else None
    change_pct = _validate(old_price, new_price)
    dry_run = await _effective_dry_run(
        session, tenant_id, acc, "adgroup_bid", bid_change_pct=change_pct
    )
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session, WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.action_type == "set_adgroup_bid",
            WritebackAction.adgroup_id == adgroup_id,
        )
    effective_approval_id = await _claim_funds_approval(
        session,
        approval_id=approval_id,
        tenant_id=tenant_id,
        action_type=ACTION_ADGROUP_BID,
        payload={"adgroup_id": adgroup_id, "new_price": new_price},
        operator_user_id=operator_user_id,
        dry_run=dry_run,
        confirmation=confirmation,
        idempotency_key=idempotency_key,
    )
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id, action_type="set_adgroup_bid",
        approval_id=effective_approval_id,
        word=adg.adgroup_name or f"单元#{adgroup_id}",
        campaign_id=adg.campaign_id, adgroup_id=adgroup_id, adgroup_name=adg.adgroup_name,
        old_value=old_price, new_value=new_price,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    await _persist_funds_intent(session, rec, dry_run=dry_run)
    if not dry_run:
        await session.refresh(adg, with_for_update=True)
        if camp is not None:
            await session.refresh(camp, with_for_update=True)
            if camp.budget is not None and new_price > float(camp.budget):
                exc = WritebackError(
                    f"单元出价 {new_price} 不能超过所属计划日预算 {float(camp.budget):.2f}"
                )
                rec.status = "failed"
                rec.error_msg = f"执行前复核失败：{exc}"
                rec.executed_at = datetime.utcnow()
                await session.commit()
                raise exc
        await _relock_funds_account(session, acc, rec)
        await session.refresh(rec, with_for_update=True)
        rec.old_value = float(adg.max_price) if adg.max_price is not None else None
    try:
        resp = await AdgroupService(_account_client(acc)).update_adgroup_fields(
            adgroup_id, max_price=new_price
        )
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            adg.max_price = new_price
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("单元出价写回失败 adgroup=%s price=%s: %s", adgroup_id, new_price, e)
    except Exception as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("单元出价写回异常 adgroup=%s", adgroup_id)

    await session.commit()
    await session.refresh(rec)
    return rec


def _clean_url_field(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


def _validate_landing_url(value: str | None, label: str) -> str | None:
    value = _clean_url_field(value)
    if value in (None, ""):
        return value
    if not (value.startswith("http://") or value.startswith("https://")):
        raise WritebackError(f"{label} 必须以 http:// 或 https:// 开头")
    if len(value.encode("utf-8")) > 1024:
        raise WritebackError(f"{label} 不能超过 1024 字节")
    return value


async def apply_adgroup_landing_url_writeback(
    session: AsyncSession,
    tenant_id: int,
    adgroup_id: int,
    *,
    pc_final_url: str | None,
    mobile_final_url: str | None,
    pc_track_param: str | None,
    mobile_track_param: str | None,
    pc_track_template: str | None,
    mobile_track_template: str | None,
    operator_user_id: int | None,
    operator_name: str | None,
) -> WritebackAction:
    """单元最终访问网址/监控字段写回（updateAdgroup）。dry-run 时只记台账不真发。"""
    adg = await session.scalar(
        select(Adgroup).where(
            Adgroup.tenant_id == tenant_id, Adgroup.adgroup_id == adgroup_id
        ).with_for_update()
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    acc = await _active_account(session, tenant_id, _asset_account_id(adg, "单元"))

    pc_final_url = _validate_landing_url(pc_final_url, "PC 最终访问网址")
    mobile_final_url = _validate_landing_url(mobile_final_url, "移动最终访问网址")
    pc_track_param = _clean_url_field(pc_track_param)
    mobile_track_param = _clean_url_field(mobile_track_param)
    pc_track_template = _clean_url_field(pc_track_template)
    mobile_track_template = _clean_url_field(mobile_track_template)

    old_snapshot = {
        "pcFinalUrl": adg.pc_final_url,
        "mobileFinalUrl": adg.mobile_final_url,
        "pcTrackParam": adg.pc_track_param,
        "mobileTrackParam": adg.mobile_track_param,
        "pcTrackTemplate": adg.pc_track_template,
        "mobileTrackTemplate": adg.mobile_track_template,
    }
    new_snapshot = {
        "pcFinalUrl": pc_final_url,
        "mobileFinalUrl": mobile_final_url,
        "pcTrackParam": pc_track_param,
        "mobileTrackParam": mobile_track_param,
        "pcTrackTemplate": pc_track_template,
        "mobileTrackTemplate": mobile_track_template,
    }
    if old_snapshot == new_snapshot:
        raise WritebackError("落地页设置没有变化")

    dry_run = await _effective_dry_run(session, tenant_id, acc, "adgroup_landing_url")
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session,
            WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.adgroup_id == adgroup_id,
            WritebackAction.action_type == "set_adgroup_url",
        )
    rec = WritebackAction(
        tenant_id=tenant_id,
        baidu_account_id=acc.id,
        action_type="set_adgroup_url",
        word=adg.adgroup_name or f"单元#{adgroup_id}",
        campaign_id=adg.campaign_id,
        adgroup_id=adgroup_id,
        adgroup_name=adg.adgroup_name,
        dry_run=dry_run,
        status="pending",
        baidu_response=f"old={old_snapshot}; new={new_snapshot}"[:2000],
        operator_user_id=operator_user_id,
        operator_name=operator_name,
    )
    await _persist_action_intent(
        session, rec, dry_run=dry_run, asset=adg, account=acc
    )
    if not dry_run:
        latest_snapshot = {
            "pcFinalUrl": adg.pc_final_url,
            "mobileFinalUrl": adg.mobile_final_url,
            "pcTrackParam": adg.pc_track_param,
            "mobileTrackParam": adg.mobile_track_param,
            "pcTrackTemplate": adg.pc_track_template,
            "mobileTrackTemplate": adg.mobile_track_template,
        }
        if latest_snapshot != old_snapshot:
            await _fail_action_preflight(session, rec, "单元落地页设置已变化，请核对后重试")
    try:
        resp = await AdgroupService(_account_client(acc)).update_adgroup_fields(
            adgroup_id,
            pc_final_url=pc_final_url,
            mobile_final_url=mobile_final_url,
            pc_track_param=pc_track_param,
            mobile_track_param=mobile_track_param,
            pc_track_template=pc_track_template,
            mobile_track_template=mobile_track_template,
        )
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str({"old": old_snapshot, "new": new_snapshot, "baidu": resp})[:2000]
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            adg.pc_final_url = pc_final_url
            adg.mobile_final_url = mobile_final_url
            adg.pc_track_param = pc_track_param
            adg.mobile_track_param = mobile_track_param
            adg.pc_track_template = pc_track_template
            adg.mobile_track_template = mobile_track_template
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("单元落地页写回失败 adgroup=%s: %s", adgroup_id, e)
    except Exception as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("单元落地页写回异常 adgroup=%s", adgroup_id)

    await session.commit()
    await session.refresh(rec)
    return rec


# ===== 账户日预算写回（投放管理：安全总闸，L1 引导第一步） =====


async def apply_account_budget_writeback(
    session: AsyncSession,
    tenant_id: int,
    new_budget: float,
    *,
    operator_user_id: int | None,
    operator_name: str | None,
    approval_id: int | None = None,
    confirmation: str | None = None,
    idempotency_key: str | None = None,
    baidu_account_id: int | None = None,
) -> WritebackAction:
    """账户日预算写回（updateAccountInfo budget，文档 0036）。dry_run 时拦截不真发。

    旧预算实时查 getAccountInfo 作快照（账户预算不存本地表）。校验合法区间 [50, 1e7]。
    账户级操作无 keyword/campaign，台账用 word='账户日预算' + old_value/new_value 记前后值。
    """
    new_budget = round(float(new_budget), 2)
    if new_budget < MIN_ACCOUNT_BUDGET or new_budget > MAX_ACCOUNT_BUDGET:
        raise WritebackError(
            f"账户日预算 {new_budget} 超出合法区间 "
            f"[{MIN_ACCOUNT_BUDGET:.0f}, {MAX_ACCOUNT_BUDGET:.0f}]"
        )
    acc = await _preflight_active_account(session, tenant_id, baidu_account_id)
    preflight_account_id = acc.id

    # 实时查当前账户预算作旧值快照（失败不阻断写回，old_value 留空）
    old_budget: float | None = None
    try:
        info = (await AccountService(_account_client(acc)).get_account_info(
            ["budget", "budgetType"]
        )).get("data") or {}
        if isinstance(info, list):
            info = info[0] if info else {}
        b = info.get("budget")
        old_budget = round(float(b), 2) if b is not None else None
    except Exception:  # noqa: BLE001  查旧值失败不该挡住写回
        logger.warning("账户预算写回：查当前预算失败，old_value 留空", exc_info=True)

    # 只在外部预读取完成后锁定账户。使用原调用选择条件重新查询，既保留
    # 多账户歧义保护，也能发现预读取期间账户被停用或归属发生变化。
    acc = await _active_account(session, tenant_id, baidu_account_id)
    if acc.id != preflight_account_id:
        raise WritebackError("推广账户状态已变化，请重试")

    dry_run = await _effective_dry_run(session, tenant_id, acc, "account_budget")
    if not dry_run:
        await _ensure_no_unresolved_funds_writeback(
            session, WritebackAction,
            WritebackAction.tenant_id == tenant_id,
            WritebackAction.baidu_account_id == acc.id,
            WritebackAction.action_type == "set_account_budget",
        )
    effective_approval_id = await _claim_funds_approval(
        session,
        approval_id=approval_id,
        tenant_id=tenant_id,
        action_type=ACTION_ACCOUNT_BUDGET,
        payload={"baidu_account_id": acc.id, "new_budget": new_budget},
        operator_user_id=operator_user_id,
        dry_run=dry_run,
        confirmation=confirmation,
        idempotency_key=idempotency_key,
    )
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id, action_type="set_account_budget",
        approval_id=effective_approval_id,
        word="账户日预算", old_value=old_budget, new_value=new_budget,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    await _persist_funds_intent(session, rec, dry_run=dry_run)
    if not dry_run:
        # 账户行作为账户级写操作互斥锁；锁持有到最终状态提交。
        await _relock_funds_account(session, acc, rec)
        await session.refresh(rec, with_for_update=True)
    try:
        resp = await AccountService(_account_client(acc)).update_account_budget(
            new_budget, budget_type=1
        )
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
    except BaiduAPIError as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.warning("账户预算写回失败 tenant=%s budget=%s: %s", tenant_id, new_budget, e)
    except Exception as e:
        _record_writeback_exception(rec, e, dry_run=dry_run)
        logger.exception("账户预算写回异常 tenant=%s", tenant_id)

    await session.commit()
    await session.refresh(rec)
    return rec

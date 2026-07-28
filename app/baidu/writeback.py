"""调价回写编排：把 AI/人工确认后的出价写回百度（updateWord），逐条落台账。

安全分层：
  1. config.baidu_write_dry_run 演练开关（默认 True）——开启时 client 拦截不真发；
  2. 本模块业务校验——渐进调价 20% 硬上限 + 出价合法区间，越界直接拒绝；
  3. bid_writebacks 台账——旧价快照 + 目标价 + 是否演练 + 百度返回 + 操作人，全程留痕。
红线见 memory feedback-no-baidu-writeback：功能要做，但验证阶段绝不改乱线上真实出价。
"""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu.client import BaiduAPIError
from app.baidu.services.account import AccountService
from app.baidu.services.adgroup import AdgroupService
from app.baidu.services.campaign import CampaignService
from app.baidu.services.keyword import KeywordService
from app.baidu.sync import _account_client
from app.config import get_settings
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


class WritebackError(Exception):
    """回写前校验失败（业务拒绝，不调百度）。"""


def _validate(old_bid: float | None, new_bid: float) -> float | None:
    """校验目标价，返回 change_pct（无旧价则 None）。越界抛 WritebackError。"""
    if new_bid < MIN_BID or new_bid > MAX_BID:
        raise WritebackError(f"目标出价 {new_bid} 超出合法区间 [{MIN_BID}, {MAX_BID}]")
    if old_bid is None or old_bid <= 0:
        return None
    change_pct = abs(new_bid - old_bid) / old_bid * 100
    if change_pct > MAX_CHANGE_PCT + 1e-6:
        raise WritebackError(
            f"调价幅度 {change_pct:.1f}% 超过渐进调价硬上限 {MAX_CHANGE_PCT:.0f}%"
            f"（{old_bid} → {new_bid}）"
        )
    return round(change_pct, 2)


async def apply_keyword_writeback(
    session: AsyncSession,
    tenant_id: int,
    keyword_id: int,
    new_bid: float,
    *,
    operator_user_id: int | None,
    operator_name: str | None,
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
        )
    )
    if kw is None:
        raise WritebackError("关键词不在维度表中，请先执行关键词维度同步")

    old_bid = float(kw.price) if kw.price is not None else None
    new_bid = round(float(new_bid), 2)
    change_pct = _validate(old_bid, new_bid)

    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id,
            BaiduAccount.status == "active",
        )
    )
    if acc is None:
        raise WritebackError("该租户没有生效的百度账户授权，无法回写")

    # 关联当下 pending 建议（可选）：用于记录来源 + 真写成功后标采纳
    sug = await session.scalar(
        select(Suggestion).where(
            Suggestion.tenant_id == tenant_id,
            Suggestion.keyword_id == keyword_id,
            Suggestion.status == "pending",
        )
    )

    dry_run = get_settings().baidu_write_dry_run

    rec = BidWriteback(
        tenant_id=tenant_id,
        baidu_account_id=acc.id,
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
    session.add(rec)
    await session.flush()  # 拿到 id，并先把 pending 记入本事务

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
        rec.status = "failed"
        rec.error_msg = f"[{e.code}] {e.message}"[:2000]
        rec.executed_at = datetime.utcnow()
        logger.warning("回写失败 keyword_id=%s: %s", keyword_id, e)
    except Exception as e:  # 网络/未知错误也落台账，不静默
        rec.status = "failed"
        rec.error_msg = str(e)[:2000]
        rec.executed_at = datetime.utcnow()
        logger.exception("回写异常 keyword_id=%s", keyword_id)

    await session.commit()
    await session.refresh(rec)
    return rec


# ===== 加否词 / 转拓词（搜索词页发起，非出价类，记 writeback_actions） =====

# 匹配方式 → 百度 addWord (matchType, phraseType)（文档 0064/0068 核对）：
# 精确=1+1、短语=2+1、智能=2+3。两者必须配合传，否则百度按默认细分匹配处理。
_MATCH_BY_MODE = {"exact": (1, 1), "phrase": (2, 1)}


async def _active_account(session: AsyncSession, tenant_id: int) -> BaiduAccount:
    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active"
        )
    )
    if acc is None:
        raise WritebackError("该租户没有生效的百度账户授权，无法回写")
    return acc


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
        select(Adgroup).where(Adgroup.tenant_id == tenant_id, Adgroup.adgroup_id == adgroup_id)
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    acc = await _active_account(session, tenant_id)

    field = "exact_negative_words" if match_mode == "exact" else "negative_words"
    current = list(getattr(adg, field) or [])
    if word in current:
        raise WritebackError(f"「{word}」已在该单元的{'精确' if match_mode == 'exact' else '短语'}否词中")
    new_list = current + [word]

    dry_run = get_settings().baidu_write_dry_run
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id, action_type="negative",
        word=word, match_mode=match_mode,
        campaign_id=adg.campaign_id, adgroup_id=adgroup_id, adgroup_name=adg.adgroup_name,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    session.add(rec)
    await session.flush()

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
        rec.status = "failed"
        rec.error_msg = f"[{e.code}] {e.message}"[:2000]
        rec.executed_at = datetime.utcnow()
        logger.warning("加否词失败 adgroup=%s word=%s: %s", adgroup_id, word, e)
    except Exception as e:
        rec.status = "failed"
        rec.error_msg = str(e)[:2000]
        rec.executed_at = datetime.utcnow()
        logger.exception("加否词异常 adgroup=%s word=%s", adgroup_id, word)

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
    """把搜索词加成正式关键词（addWord）到指定单元。match_mode: exact/phrase。

    出价受合法区间校验。dry_run 时拦截不真发。
    """
    word = (word or "").strip()
    if not word:
        raise WritebackError("关键词不能为空")
    if match_mode not in ("exact", "phrase"):
        raise WritebackError("匹配方式只能是 exact / phrase")
    price = round(float(price), 2)
    if price < MIN_BID or price > MAX_BID:
        raise WritebackError(f"出价 {price} 超出合法区间 [{MIN_BID}, {MAX_BID}]")

    adg = await session.scalar(
        select(Adgroup).where(Adgroup.tenant_id == tenant_id, Adgroup.adgroup_id == adgroup_id)
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    acc = await _active_account(session, tenant_id)

    dry_run = get_settings().baidu_write_dry_run
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id, action_type="add_word",
        word=word, match_mode=match_mode, price=price,
        campaign_id=adg.campaign_id, adgroup_id=adgroup_id, adgroup_name=adg.adgroup_name,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    session.add(rec)
    await session.flush()

    try:
        svc = KeywordService(_account_client(acc))
        match_type, phrase_type = _MATCH_BY_MODE[match_mode]
        resp = await svc.add_word(adgroup_id, word, match_type, phrase_type, price)
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
    except BaiduAPIError as e:
        rec.status = "failed"
        rec.error_msg = f"[{e.code}] {e.message}"[:2000]
        rec.executed_at = datetime.utcnow()
        logger.warning("转拓词失败 adgroup=%s word=%s: %s", adgroup_id, word, e)
    except Exception as e:
        rec.status = "failed"
        rec.error_msg = str(e)[:2000]
        rec.executed_at = datetime.utcnow()
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
        select(Keyword).where(Keyword.tenant_id == tenant_id, Keyword.keyword_id == keyword_id)
    )
    if kw is None:
        raise WritebackError("关键词不在维度表中，请先执行关键词维度同步")
    acc = await _active_account(session, tenant_id)

    dry_run = get_settings().baidu_write_dry_run
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id,
        action_type="pause" if pause else "enable",
        word=kw.keyword, campaign_id=kw.campaign_id, adgroup_id=kw.adgroup_id,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    session.add(rec)
    await session.flush()
    try:
        svc = KeywordService(_account_client(acc))
        resp = await svc.update_word_pause(keyword_id, pause)
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
        if not dry_run:
            kw.pause = pause
    except BaiduAPIError as e:
        rec.status = "failed"
        rec.error_msg = f"[{e.code}] {e.message}"[:2000]
        rec.executed_at = datetime.utcnow()
        logger.warning("启停失败 keyword_id=%s pause=%s: %s", keyword_id, pause, e)
    except Exception:
        rec.status = "failed"
        rec.error_msg = "未知错误"
        rec.executed_at = datetime.utcnow()
        logger.exception("启停异常 keyword_id=%s", keyword_id)

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
        select(Adgroup).where(Adgroup.tenant_id == tenant_id, Adgroup.adgroup_id == adgroup_id)
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    acc = await _active_account(session, tenant_id)

    field = "exact_negative_words" if match_mode == "exact" else "negative_words"
    current = list(getattr(adg, field) or [])
    if word not in current:
        raise WritebackError(f"「{word}」不在该单元的{'精确' if match_mode == 'exact' else '短语'}否词中")
    new_list = [w for w in current if w != word]

    dry_run = get_settings().baidu_write_dry_run
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id, action_type="remove_negative",
        word=word, match_mode=match_mode,
        campaign_id=adg.campaign_id, adgroup_id=adgroup_id, adgroup_name=adg.adgroup_name,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    session.add(rec)
    await session.flush()
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
        rec.status = "failed"
        rec.error_msg = f"[{e.code}] {e.message}"[:2000]
        rec.executed_at = datetime.utcnow()
        logger.warning("删否词失败 adgroup=%s word=%s: %s", adgroup_id, word, e)
    except Exception:
        rec.status = "failed"
        rec.error_msg = "未知错误"
        rec.executed_at = datetime.utcnow()
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
    camp = await session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == tenant_id, Campaign.campaign_id == campaign_id
        )
    )
    if camp is None:
        raise WritebackError("计划不在维度表中，请先执行计划维度同步")
    acc = await _active_account(session, tenant_id)

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

    old_budget = float(camp.budget) if camp.budget is not None else None
    dry_run = get_settings().baidu_write_dry_run
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id, action_type="set_campaign_budget",
        word=camp.campaign_name or f"计划#{campaign_id}",
        campaign_id=campaign_id, campaign_name=camp.campaign_name,
        old_value=old_budget, new_value=new_budget,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    session.add(rec)
    await session.flush()
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
        rec.status = "failed"
        rec.error_msg = f"[{e.code}] {e.message}"[:2000]
        rec.executed_at = datetime.utcnow()
        logger.warning("计划预算写回失败 campaign=%s budget=%s: %s", campaign_id, new_budget, e)
    except Exception:
        rec.status = "failed"
        rec.error_msg = "未知错误"
        rec.executed_at = datetime.utcnow()
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
        )
    )
    if camp is None:
        raise WritebackError("计划不在维度表中，请先执行计划维度同步")
    acc = await _active_account(session, tenant_id)

    dry_run = get_settings().baidu_write_dry_run
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id,
        action_type="campaign_pause" if pause else "campaign_enable",
        word=camp.campaign_name or f"计划#{campaign_id}",
        campaign_id=campaign_id, campaign_name=camp.campaign_name,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    session.add(rec)
    await session.flush()
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
        rec.status = "failed"
        rec.error_msg = f"[{e.code}] {e.message}"[:2000]
        rec.executed_at = datetime.utcnow()
        logger.warning("计划启停失败 campaign=%s pause=%s: %s", campaign_id, pause, e)
    except Exception:
        rec.status = "failed"
        rec.error_msg = "未知错误"
        rec.executed_at = datetime.utcnow()
        logger.exception("计划启停异常 campaign=%s", campaign_id)

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
        )
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    acc = await _active_account(session, tenant_id)

    dry_run = get_settings().baidu_write_dry_run
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id,
        action_type="adgroup_pause" if pause else "adgroup_enable",
        word=adg.adgroup_name or f"单元#{adgroup_id}",
        campaign_id=adg.campaign_id, adgroup_id=adgroup_id, adgroup_name=adg.adgroup_name,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    session.add(rec)
    await session.flush()
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
        rec.status = "failed"
        rec.error_msg = f"[{e.code}] {e.message}"[:2000]
        rec.executed_at = datetime.utcnow()
        logger.warning("单元启停失败 adgroup=%s pause=%s: %s", adgroup_id, pause, e)
    except Exception:
        rec.status = "failed"
        rec.error_msg = "未知错误"
        rec.executed_at = datetime.utcnow()
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
        )
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    # 单元出价不能超所属计划预算（本地有预算时预校验）
    if adg.campaign_id is not None:
        camp = await session.scalar(
            select(Campaign).where(
                Campaign.tenant_id == tenant_id, Campaign.campaign_id == adg.campaign_id
            )
        )
        if camp is not None and camp.budget is not None and new_price > float(camp.budget):
            raise WritebackError(
                f"单元出价 {new_price} 不能超过所属计划日预算 {float(camp.budget):.2f}"
            )
    acc = await _active_account(session, tenant_id)

    old_price = float(adg.max_price) if adg.max_price is not None else None
    dry_run = get_settings().baidu_write_dry_run
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id, action_type="set_adgroup_bid",
        word=adg.adgroup_name or f"单元#{adgroup_id}",
        campaign_id=adg.campaign_id, adgroup_id=adgroup_id, adgroup_name=adg.adgroup_name,
        old_value=old_price, new_value=new_price,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    session.add(rec)
    await session.flush()
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
        rec.status = "failed"
        rec.error_msg = f"[{e.code}] {e.message}"[:2000]
        rec.executed_at = datetime.utcnow()
        logger.warning("单元出价写回失败 adgroup=%s price=%s: %s", adgroup_id, new_price, e)
    except Exception:
        rec.status = "failed"
        rec.error_msg = "未知错误"
        rec.executed_at = datetime.utcnow()
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
        )
    )
    if adg is None:
        raise WritebackError("单元不在维度表中，请先执行单元维度同步")
    acc = await _active_account(session, tenant_id)

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

    dry_run = get_settings().baidu_write_dry_run
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
    session.add(rec)
    await session.flush()
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
        rec.status = "failed"
        rec.error_msg = f"[{e.code}] {e.message}"[:2000]
        rec.executed_at = datetime.utcnow()
        logger.warning("单元落地页写回失败 adgroup=%s: %s", adgroup_id, e)
    except Exception:
        rec.status = "failed"
        rec.error_msg = "未知错误"
        rec.executed_at = datetime.utcnow()
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
    acc = await _active_account(session, tenant_id)

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

    dry_run = get_settings().baidu_write_dry_run
    rec = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=acc.id, action_type="set_account_budget",
        word="账户日预算", old_value=old_budget, new_value=new_budget,
        dry_run=dry_run, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    session.add(rec)
    await session.flush()
    try:
        resp = await AccountService(_account_client(acc)).update_account_budget(
            new_budget, budget_type=1
        )
        rec.status = "dry_run" if dry_run else "success"
        rec.baidu_response = str(resp)[:2000]
        rec.executed_at = datetime.utcnow()
    except BaiduAPIError as e:
        rec.status = "failed"
        rec.error_msg = f"[{e.code}] {e.message}"[:2000]
        rec.executed_at = datetime.utcnow()
        logger.warning("账户预算写回失败 tenant=%s budget=%s: %s", tenant_id, new_budget, e)
    except Exception:
        rec.status = "failed"
        rec.error_msg = "未知错误"
        rec.executed_at = datetime.utcnow()
        logger.exception("账户预算写回异常 tenant=%s", tenant_id)

    await session.commit()
    await session.refresh(rec)
    return rec

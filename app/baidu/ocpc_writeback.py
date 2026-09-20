"""oCPC 单策略调价：独立开关、绑定审批、持久化意图与保守对账。"""
import json
from datetime import datetime

from sqlalchemy import select

from app.baidu.services.account import AccountService
from app.baidu.services.ocpc import OcpcService, normalize_ocpc_bid
from app.baidu.sync import _account_client
from app.baidu.writeback import (
    WritebackError, _active_account, _ensure_no_unresolved_funds_writeback,
    _persist_funds_intent, _effective_dry_run, _claim_funds_approval,
)
from app.config import get_settings
from app.models import OcpcPackage, WritebackAction, TenantModule
from app.sem_live_write_policy import evaluate_live_write_grant


def ocpc_dry_run():
    settings = get_settings()
    return (settings.baidu_write_dry_run or not settings.baidu_ocpc_write_enabled
            or settings.baidu_legacy_split_confirmation_enabled)


async def ocpc_execution_mode(session, tenant_id, account_id):
    if ocpc_dry_run() or not account_id:
        return "dry_run"
    module = await session.scalar(select(TenantModule).where(
        TenantModule.tenant_id == tenant_id, TenantModule.module_code == "sem"))
    decision = evaluate_live_write_grant(get_settings(), module, tenant_id=tenant_id,
                                        account_id=account_id, write_scope="ocpc_bid")
    return "dry_run" if decision.dry_run else "live"


async def apply_ocpc_bid(session, *, tenant_id, package_id, baidu_account_id,
                         old_bid, new_bid, execution_mode, approval_id,
                         operator_user_id, operator_name, confirmation=None, idempotency_key=None):
    try:
        old_bid = normalize_ocpc_bid(old_bid)
        new_bid = normalize_ocpc_bid(new_bid)
    except ValueError as exc:
        raise WritebackError(str(exc)) from exc
    if operator_user_id is None:
        raise WritebackError("oCPC 调价必须使用实名登录账号")
    if old_bid == new_bid:
        raise WritebackError("目标转化出价未变化")
    if abs(new_bid - old_bid) / old_bid > 0.20 + 1e-9:
        raise WritebackError("单次调价幅度不得超过 20%")
    dry_run = ocpc_dry_run()
    # 账户优先加锁，串行化同账户 oCPC 操作，且不猜测资产归属。
    account = await _active_account(session, tenant_id, baidu_account_id)
    package = await session.scalar(select(OcpcPackage).where(
        OcpcPackage.tenant_id == tenant_id,
        OcpcPackage.package_id == package_id,
        OcpcPackage.baidu_account_id == baidu_account_id,
    ).with_for_update())
    if package is None:
        raise WritebackError("策略不属于当前客户和推广账户，请重新同步")
    def validate_package():
        if package.ocpc_bid_type != 1:
            raise WritebackError("仅支持目标转化成本模式，不能修改增强模式")
        if package.ocpc_bid is None or float(package.ocpc_bid) != old_bid:
            raise WritebackError("策略出价已变化，请刷新并重新确认")
    validate_package()
    if not dry_run:
        dry_run = await _effective_dry_run(session, tenant_id, account, "ocpc_bid",
            bid_change_pct=abs(new_bid - old_bid) / old_bid * 100)
    if execution_mode != ("dry_run" if dry_run else "live"):
        raise WritebackError("执行模式已变化，请刷新并重新确认")
    await _ensure_no_unresolved_funds_writeback(
        session, WritebackAction,
        WritebackAction.tenant_id == tenant_id,
        WritebackAction.baidu_account_id == baidu_account_id,
        WritebackAction.action_type == "set_ocpc_bid",
    )
    payload = {"package_id": package_id, "baidu_account_id": baidu_account_id,
               "old_bid": old_bid, "new_bid": new_bid}
    if not dry_run:
        approval_id = await _claim_funds_approval(
            session, approval_id=approval_id, tenant_id=tenant_id,
            action_type="ocpc_bid", payload=payload, operator_user_id=operator_user_id,
            dry_run=False, confirmation=confirmation, idempotency_key=idempotency_key)
    record = WritebackAction(
        tenant_id=tenant_id, baidu_account_id=baidu_account_id,
        action_type="set_ocpc_bid", word=f"oCPC #{package_id} · {package.package_name or ''}",
        old_value=old_bid, new_value=new_bid, dry_run=dry_run,
        approval_id=approval_id if not dry_run else None, status="pending",
        operator_user_id=operator_user_id, operator_name=operator_name,
    )
    await _persist_funds_intent(session, record, dry_run=dry_run)
    if dry_run:
        # 不构造百度客户端，不读取凭据，不发送任何外部请求。
        record.status = "dry_run"
    else:
        attempted_write = False
        try:
            await session.refresh(account, with_for_update=True)
            await session.refresh(package, with_for_update=True)
            await session.refresh(record, with_for_update=True)
            if record.status != "pending":
                raise WritebackError("执行记录状态已变化，请核对台账")
            if account.status != "active" or account.tenant_id != tenant_id:
                raise WritebackError("账户授权或客户归属已变化")
            if package.tenant_id != tenant_id or package.baidu_account_id != baidu_account_id:
                raise WritebackError("策略归属已变化")
            if ocpc_dry_run():
                raise WritebackError("执行开关已变化，请重新确认")
            validate_package()
            if await _effective_dry_run(session, tenant_id, account, "ocpc_bid",
                    requested_attempts=0, bid_change_pct=abs(new_bid - old_bid) / old_bid * 100):
                raise WritebackError("账户调价授权已变化，请重新确认")
            client = _account_client(account)
            service = OcpcService(client)
            # 只读复核百度最新价格，拒绝覆盖后台已经发生的调价。
            info = (await AccountService(client).get_account_info(["userId"])).get("data") or {}
            if isinstance(info, list):
                info = info[0] if len(info) == 1 else {}
            user_id = info.get("userId")
            if not user_id or isinstance(user_id, bool):
                raise WritebackError("无法核实百度推广账户 ID")
            remote = await service.get_target_packages(int(user_id))
            matches = [p for p in remote if p.get("targetPackageId") == package_id]
            if len(matches) != 1 or matches[0].get("ocpcBidType") != 1:
                raise WritebackError("百度策略或出价模式已变化，请重新同步")
            if normalize_ocpc_bid(matches[0].get("ocpcBid")) != old_bid:
                raise WritebackError("百度目标转化出价已变化，请重新同步后申请审批")
            attempted_write = True
            response = await service.update_target_bid(package_id, new_bid)
            rows = response.get("data") or []
            if response.get("_dry_run") or not isinstance(rows, list) or len(rows) != 1:
                raise WritebackError("百度未返回唯一的策略更新结果")
            if rows[0].get("targetPackageId") != package_id or normalize_ocpc_bid(rows[0].get("ocpcBid")) != new_bid:
                raise WritebackError("百度返回的策略或价格与提交内容不一致")
            record.status = "success"
            package.ocpc_bid = new_bid
            package.raw = {**(package.raw or {}), "ocpcBid": new_bid}
            record.baidu_response = json.dumps({"package_id": package_id, "ocpcBid": new_bid})
        except Exception:
            # HTTP 失败/不完整响应不能证明百度未执行，保留已消费审批并禁止重试。
            record.status = "reconcile" if attempted_write else "failed"
            record.error_msg = ("百度执行结果未确认，请到行动台账人工对账，勿重复提交"
                                if attempted_write else "执行前复核失败，未发送调价请求；请重新同步策略并核对账户授权")
    record.executed_at = datetime.utcnow()
    await session.commit()
    await session.refresh(record)
    return record

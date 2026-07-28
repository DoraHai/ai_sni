"""还原演练痕迹：删除台账里 status='dry_run' 的记录（bid_writebacks + writeback_actions）。

dry-run 模式不改任何业务数据（关键词价格/启停/否词/建议状态只有真写成功才落地），
演练唯一产生的是这两张台账里的 dry_run 行。测完切回正式前跑此脚本清掉即可还原。

用法（ECS 上）：
    # 只清某时刻之后的（推荐：测试前记下时间，避免误删历史演练记录）
    cd /opt/sem-backend && sudo -u sem PYTHONPATH=/opt/sem-backend .venv/bin/python \
        scripts/purge_dryrun.py --since "2026-06-27 00:00:00"
    # 清全部 dry_run 行
    ... scripts/purge_dryrun.py --all
    # 只看不删（预览）
    ... scripts/purge_dryrun.py --all --dry
"""
import argparse
import asyncio
from datetime import datetime

from sqlalchemy import delete, func, select

from app.database import async_session_factory
from app.models import BidWriteback, WritebackAction


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="只清此时间之后创建的 dry_run 行，格式 'YYYY-MM-DD HH:MM:SS'")
    ap.add_argument("--all", action="store_true", help="清全部 dry_run 行")
    ap.add_argument("--dry", action="store_true", help="只统计不删除（预览）")
    args = ap.parse_args()

    if not args.since and not args.all:
        ap.error("必须指定 --since '时间' 或 --all")
    since = datetime.fromisoformat(args.since) if args.since else None

    async with async_session_factory() as s:
        for model, name in ((BidWriteback, "bid_writebacks"), (WritebackAction, "writeback_actions")):
            cond = [model.status == "dry_run"]
            if since is not None:
                cond.append(model.created_at >= since)
            n = await s.scalar(select(func.count()).select_from(model).where(*cond))
            if args.dry:
                print(f"[预览] {name} 待清 dry_run 行：{n}")
            else:
                await s.execute(delete(model).where(*cond))
                print(f"{name} 已删 dry_run 行：{n}")
        if not args.dry:
            await s.commit()
    scope = f"since {since}" if since else "全部"
    print(f"完成（范围：{scope}）。业务数据未受影响，仅清演练台账痕迹。")


if __name__ == "__main__":
    asyncio.run(main())

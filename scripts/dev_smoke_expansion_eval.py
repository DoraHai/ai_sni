"""拓词候选 AI 评估冒烟（AI 应用路线 ②）：批量评估器（mock DeepSeek）+ 接口筛选/计数。

覆盖：按词去重批量评估、同词多源统一回写、通用噪音识别、adopted 不评、
幂等跳过已评 / force 重评、未配 key 降级、单批失败容错+部分提交、接口 ai_relevance 筛选/计数/导出列。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_expansion_eval.py
"""
import asyncio
import json
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import delete, func, select, update

from app.ai.deepseek import DeepSeekError
from app.ai.expansion_eval import (
    _build_user_prompt,
    _valid,
    evaluate_candidates_for_tenant,
)
from app.database import async_session_factory, engine
from app.models import BaiduAccount, KeywordCandidate, Tenant
from app.security.crypto import encrypt

failed = False


def check(label: str, cond: bool, detail: str = "") -> None:
    global failed
    mark = "✅" if cond else "❌"
    if not cond:
        failed = True
    print(f"{mark} {label} {detail}")


# 评估词 → (relevance, recommend, reason)。mock 从 prompt 里解析词后据此回填
VERDICTS = {
    "多级离心泵 选型": ("relevant", "adopt", "核心产品词，建议拓展"),
    "化工分离塔 设计": ("relevant", "watch", "相关但量不确定"),
    "磁力泵 价格": ("relevant", "adopt", "强采购意图"),
    "冒烟泵业 招聘": ("irrelevant", "drop", "招聘非业务相关"),
    "设备": ("generic", "drop", "通用词无商业指向"),
}


def _parse_words(user_prompt: str) -> list[str]:
    """从 _build_user_prompt 的 '- word（meta）' 行里取词。"""
    out = []
    for line in user_prompt.splitlines():
        line = line.strip()
        if line.startswith("- "):
            out.append(line[2:].split("（")[0].strip())
    return out


async def fake_chat_json(system: str, user: str, timeout: float = 30.0) -> dict:
    items = []
    profile = json.loads(user.splitlines()[1])
    for w in _parse_words(user):
        if w in VERDICTS:
            rel, rec, reason = VERDICTS[w]
            relation = {"relevant": "in_scope", "irrelevant": "out_of_scope", "generic": "generic"}[rel]
            items.append({"word": w, "relevance": rel, "recommend": rec, "reason": reason,
                          "basis": {"relation": relation, "intent": "purchase",
                                    "field": "business_desc" if relation != "generic" else None,
                                    "quote": profile["业务描述"] if relation != "generic" else None}})
    return {"items": items}


async def main() -> None:
    # ===== 纯函数 =====
    check("_valid 合法枚举", _valid("relevant", "adopt"))
    check("_valid 拒非法", not _valid("foo", "adopt") and not _valid("relevant", "bar"))

    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "拓词评估冒烟租户"))
        if tenant is None:
            tenant = Tenant(name="拓词评估冒烟租户", strategy="lead", monthly_budget=10000,
                            brand_terms=["冒烟泵业"])
            session.add(tenant)
            await session.flush()
        tenant.industry = "工业泵 / 分离技术"
        tenant.business_desc = "工业泵及化工分离设备，不经营招聘业务"
        acc = await session.scalar(select(BaiduAccount).where(BaiduAccount.tenant_id == tenant.id))
        if acc is None:
            acc = BaiduAccount(
                tenant_id=tenant.id, baidu_username="拓词评估冒烟账户", baidu_ucid=99999994,
                access_token_encrypted=encrypt("fake-token"),
                expires_at=datetime(2026, 9, 1), auth_mode="self", status="active",
            )
            session.add(acc)
            await session.flush()
        await session.execute(
            delete(KeywordCandidate).where(KeywordCandidate.tenant_id == tenant.id)
        )

        def cand(word, source, status="pending", pv=None, cat=None):
            return KeywordCandidate(
                tenant_id=tenant.id, baidu_account_id=acc.id, word=word, source=source,
                status=status, monthly_pv=pv, suggested_category=cat,
            )

        session.add_all([
            cand("多级离心泵 选型", "planner", pv=2400, cat="focus"),
            cand("多级离心泵 选型", "cold", pv=2400, cat="focus"),  # 同词多源 → 统一回写
            cand("化工分离塔 设计", "planner", pv=280, cat="normal"),
            cand("磁力泵 价格", "query", cat="negative"),
            cand("冒烟泵业 招聘", "query", cat="brand"),
            cand("设备", "url", pv=99999, cat="observe"),  # 通用噪音
            cand("已采纳词", "planner", status="adopted", cat="focus"),  # adopted 不参与评估
        ])
        await session.commit()
        tid = tenant.id

        # build_user_prompt 含词与客户上下文
        prompt = _build_user_prompt(tenant, [{"word": "设备", "monthly_pv": 99999, "suggested_category": "observe"}])
        check("prompt 含客户/行业上下文", "冒烟泵业" in prompt and "工业泵" in prompt)
        check("prompt 列出候选词", "- 设备" in prompt and "月搜索量 99999" in prompt)

        # ===== 评估器：成功路径 =====
        with patch("app.ai.expansion_eval.is_enabled", lambda: True), \
             patch("app.ai.expansion_eval.chat_json", fake_chat_json):
            r = await evaluate_candidates_for_tenant(session, tenant)
        check("enabled True", r["enabled"] is True)
        check("按词去重 5 个", r["distinct_words"] == 5, str(r.get("distinct_words")))
        check("回写 6 行（6 个 pending 行）", r["evaluated"] == 6, str(r["evaluated"]))
        check("无失败批次", r["failed_batches"] == 0, str(r["failed_batches"]))

        async def relof(word, source):
            return await session.scalar(
                select(KeywordCandidate.ai_relevance).where(
                    KeywordCandidate.tenant_id == tid,
                    KeywordCandidate.word == word, KeywordCandidate.source == source,
                )
            )

        check("同词多源统一回写（planner=cold=relevant）",
              await relof("多级离心泵 选型", "planner") == "relevant"
              and await relof("多级离心泵 选型", "cold") == "relevant")
        check("通用噪音识别 设备→generic", await relof("设备", "url") == "generic")
        check("不相关 招聘→irrelevant", await relof("冒烟泵业 招聘", "query") == "irrelevant")
        check("adopted 词不评估（仍 None）", await relof("已采纳词", "planner") is None)

        # 理由/建议回填
        c设备 = await session.scalar(select(KeywordCandidate).where(
            KeywordCandidate.tenant_id == tid, KeywordCandidate.word == "设备"))
        check("回填 recommend/reason", c设备.ai_recommend == "drop" and "通用词" in (c设备.ai_reason or ""))

        # ===== 幂等：再跑（非 force）应跳过已评 =====
        with patch("app.ai.expansion_eval.is_enabled", lambda: True), \
             patch("app.ai.expansion_eval.chat_json", fake_chat_json):
            r2 = await evaluate_candidates_for_tenant(session, tenant)
        check("非 force 跳过已评（evaluated=0）", r2["evaluated"] == 0, str(r2["evaluated"]))

        # ===== force 重评 =====
        with patch("app.ai.expansion_eval.is_enabled", lambda: True), \
             patch("app.ai.expansion_eval.chat_json", fake_chat_json):
            r3 = await evaluate_candidates_for_tenant(session, tenant, force=True)
        check("force 重评 6 行", r3["evaluated"] == 6, str(r3["evaluated"]))

        # ===== limit 截断：存量回填分批清空 =====
        await session.execute(
            update(KeywordCandidate).where(KeywordCandidate.tenant_id == tid)
            .values(ai_relevance=None, ai_recommend=None, ai_reason=None, ai_evaluated_at=None)
        )
        await session.commit()
        with patch("app.ai.expansion_eval.is_enabled", lambda: True), \
             patch("app.ai.expansion_eval.chat_json", fake_chat_json):
            rl1 = await evaluate_candidates_for_tenant(session, tenant, limit=2)
            rl2 = await evaluate_candidates_for_tenant(session, tenant, limit=2)
            rl3 = await evaluate_candidates_for_tenant(session, tenant, limit=2)
        check("limit=2 首次评 2 词、剩 3", rl1["distinct_words"] == 2 and rl1["remaining"] == 3,
              f"{rl1['distinct_words']}/{rl1['remaining']}")
        check("limit 续评至清空（5=2+2+1）",
              rl2["distinct_words"] == 2 and rl3["distinct_words"] == 1 and rl3["remaining"] == 0,
              f"{rl2['distinct_words']}/{rl3['distinct_words']}/{rl3['remaining']}")

        # ===== 降级：未配 key =====
        with patch("app.ai.expansion_eval.is_enabled", lambda: False):
            r4 = await evaluate_candidates_for_tenant(session, tenant)
        check("未配 key 降级 enabled False", r4["enabled"] is False)

        # ===== 单批失败容错 + 部分提交 =====
        # 先清空 ai 字段，batch_size=2 → 5 词分 3 批；第 1 批抛错，其余成功
        await session.execute(
            update(KeywordCandidate).where(KeywordCandidate.tenant_id == tid)
            .values(ai_relevance=None, ai_recommend=None, ai_reason=None, ai_evaluated_at=None)
        )
        await session.commit()
        call_n = {"i": 0}

        async def flaky(system, user, timeout=30.0):
            call_n["i"] += 1
            if call_n["i"] == 1:
                raise DeepSeekError("模拟首批超时")
            return await fake_chat_json(system, user)

        with patch("app.ai.expansion_eval.is_enabled", lambda: True), \
             patch("app.ai.expansion_eval.chat_json", flaky):
            r5 = await evaluate_candidates_for_tenant(session, tenant, batch_size=2)
        check("单批失败计数", r5["failed_batches"] == 1, str(r5["failed_batches"]))
        check("失败不阻断、部分回写", 0 < r5["evaluated"] < 6, str(r5["evaluated"]))

        # 收尾：全部评估好，留给接口段（保证有数据）
        await session.execute(
            update(KeywordCandidate).where(KeywordCandidate.tenant_id == tid)
            .values(ai_relevance=None, ai_recommend=None, ai_reason=None, ai_evaluated_at=None)
        )
        await session.commit()
    await engine.dispose()

    # ===== 接口段 =====
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    auth = {"X-API-Key": get_settings().admin_api_key}
    with patch("app.ai.expansion_eval.is_enabled", lambda: True), \
         patch("app.ai.expansion_eval.chat_json", fake_chat_json), \
         patch("app.api.expansion.ai_enabled", lambda: True), \
         TestClient(app) as client:

        def fetch(**params):
            r = client.get("/api/v1/expansion/candidates",
                           params={"tenant_id": tid, **params}, headers=auth)
            assert r.status_code == 200, r.text
            return r.json()

        # 评估前：ai_enabled True、待评估 6
        b0 = fetch()
        check("接口 ai_enabled True", b0["ai_enabled"] is True)
        check("待评估计数 6", b0["ai_unevaluated"] == 6, str(b0["ai_unevaluated"]))

        # 触发评估
        r = client.post("/api/v1/expansion/evaluate",
                        params={"tenant_id": tid}, headers=auth)
        check("evaluate 接口 200 + 回写", r.status_code == 200 and r.json()["evaluated"] == 6,
              r.text[:120])

        b1 = fetch()
        check("评估后待评估清零", b1["ai_unevaluated"] == 0, str(b1["ai_unevaluated"]))
        check("AI 相关性计数", b1["ai_relevance_counts"].get("relevant") == 4
              and b1["ai_relevance_counts"].get("generic") == 1
              and b1["ai_relevance_counts"].get("irrelevant") == 1,
              str(b1["ai_relevance_counts"]))
        check("payload 含 ai 字段",
              all("ai_relevance_label" in c for c in b1["candidates"]))

        check("ai_relevance=generic 只 1 条（设备）", fetch(ai_relevance="generic")["total"] == 1)
        check("隐藏通用噪音 relevant=4 条", fetch(ai_relevance="relevant")["total"] == 4)

        r = client.get("/api/v1/expansion/candidates/export",
                       params={"tenant_id": tid, "ai_relevance": "relevant"}, headers=auth)
        check("导出含 AI 列 + 筛选生效",
              r.status_code == 200 and "AI相关性" in r.text and "招聘" not in r.text, str(r.status_code))

        # 未配 key 时 evaluate 返回 enabled False
        with patch("app.ai.expansion_eval.is_enabled", lambda: False):
            r = client.post("/api/v1/expansion/evaluate",
                            params={"tenant_id": tid}, headers=auth)
        check("未配 key evaluate enabled False", r.json().get("enabled") is False)

        r = client.post("/api/v1/expansion/evaluate",
                        params={"tenant_id": tid + 99999}, headers=auth)
        check("evaluate 跨租户 404", r.status_code == 404)


asyncio.run(main())
print("\n冒烟失败" if failed else "\n冒烟全部通过")
raise SystemExit(1 if failed else 0)

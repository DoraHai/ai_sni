"""生产试探：getCampaign / getAdgroup 是否接受 priceRatio（移动出价比例）字段。

背景：概述文档 0052 说单元属性含"计算机/移动出价比例"，但查询文档 0056 的
adgroupFields 枚举没列；批量服务有效列名（文档 0346）计划级、单元级都有 priceRatio。
推测查询接口实际接受，文档漏列。本脚本在 ECS 上跑（读 /opt/sem-backend/.env）：

    cd /opt/sem-backend && sudo -u sem .venv/bin/python scripts/probe_price_ratio.py
"""
import asyncio
import json

from app.baidu.client import BaiduAPIClient, BaiduAPIError
from app.config import get_settings

CANDIDATES = ["priceRatio", "mobilePriceRatio", "pcPriceRatio"]


async def probe(client: BaiduAPIClient, service: str, method: str,
                fields_key: str, base_fields: list[str], extra_body: dict) -> None:
    for field in CANDIDATES:
        body = {fields_key: base_fields + [field], **extra_body}
        try:
            resp = await client.call(service, method, body)
            data = resp.get("data") or []
            sample = data[:3] if isinstance(data, list) else data
            print(f"✅ {service}.{method} 接受字段 {field}，前 3 条：")
            print(json.dumps(sample, ensure_ascii=False, indent=2))
        except BaiduAPIError as e:
            print(f"❌ {service}.{method} 字段 {field} 被拒：code={e.code} msg={e.message}")


async def main() -> None:
    s = get_settings()
    client = BaiduAPIClient(username=s.baidu_default_username,
                            access_token=s.baidu_self_access_token)

    # 计划级：campaignIds 空 = 全账户（已有约定）
    await probe(client, "CampaignService", "getCampaign",
                "campaignFields", ["campaignId", "campaignName"],
                {"campaignIds": [], "adType": 0})

    # 单元级：先拿计划 ID，再 idType=3 查单元
    camps = await client.call("CampaignService", "getCampaign",
                              {"campaignFields": ["campaignId"],
                               "campaignIds": [], "adType": 0})
    camp_ids = [c["campaignId"] for c in (camps.get("data") or [])][:5]
    print(f"\n计划 IDs（取前 5）: {camp_ids}\n")
    await probe(client, "AdgroupService", "getAdgroup",
                "adgroupFields", ["adgroupId", "adgroupName", "maxPrice"],
                {"ids": camp_ids, "idType": 3, "getTemp": 0})


if __name__ == "__main__":
    asyncio.run(main())

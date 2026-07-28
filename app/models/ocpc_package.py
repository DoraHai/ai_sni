from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# packageStatus（文档 0285）。学习相关状态是判断「OCPC 喂得饱不饱」的关键信号。
PACKAGE_STATUS_LABELS = {
    0: "未生效",
    1: "投放中",
    2: "投放中（学习中）",
    3: "投放中（学习失败）",
    4: "投放中（学习结束）",
}

# ocpcBidType（出价模式，原优化模式）
OCPC_BID_TYPE_LABELS = {
    1: "目标转化成本",  # 设 ocpcBid，百度按目标转化成本自动出价
    2: "增强模式",      # 原点击出价系数控制
}

# dataFlow（转化数据来源）。决定百度算法「看不看得到」转化。
# 文档 0285 只列到 8，但实测会返回 1000「不限」及 9/10/23/24——这套与计划对象 campaignCvSources
# （文档 0040/0044/0046）同源，按后者补全。
DATA_FLOW_LABELS = {
    1000: "不限",
    1: "网页JS布码",
    2: "线索API",
    3: "咨询工具授权",
    4: "基木鱼/度小店",
    5: "应用API",
    6: "电话数据授权",
    7: "百度智能小程序SDK",
    8: "应用SDK",
    9: "爱番番",
    10: "百度APP",
    23: "百度统计网站导入",
    24: "百度统计小程序导入",
}

# transType 目标转化类型（文档 0285，仅收录常见项；苏尔寿主用 2 电话按钮点击 / 30 电话拨通）
TRANS_TYPE_LABELS = {
    1: "咨询按钮点击",
    2: "电话按钮点击",
    3: "表单提交成功",
    5: "表单按钮点击",
    18: "留线索",
    30: "电话拨通",
    50: "预约",
    99: "其他",
}


class OcpcPackage(Base):
    """oCPC 出价策略（目标转化包），OcpcService/getTargetPackageList 同步。

    OCPC 与关键词 CPC 出价是两套机制：这里设的是「目标转化出价」ocpcBid（元/转化），
    百度算法按目标转化成本实时自动出价，不返回每次出价、只给效果。策略当前仅绑定计划级
    （scope.level=2）。是否喂得动看 packageStatus（学习中/学习失败/学习结束）+ 绑定计划的
    近期转化量。本表只读同步，写回（调 ocpcBid）后续单独做。
    """

    __tablename__ = "ocpc_packages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )

    package_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # targetPackageId
    package_name: Mapped[str | None] = mapped_column(Text)
    ocpc_bid_type: Mapped[int | None] = mapped_column(SmallInteger)  # OCPC_BID_TYPE_LABELS
    ocpc_bid: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # 目标转化出价（元/转化）
    package_status: Mapped[int | None] = mapped_column(SmallInteger)  # PACKAGE_STATUS_LABELS
    ocpc_deep_cpa: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # 深度转化出价
    deep_trans_type_mode: Mapped[int | None] = mapped_column(SmallInteger)  # 0不用/1行为/2ROI

    # scope：TargetPackageBindInfo[] [{levelId=计划ID, level=2}]，原样存
    scope: Mapped[list | None] = mapped_column(JSONB)
    # dataFlowData：TargetPackageDataflowInfo[] [{dataFlow, transType[]}]——转化口径，原样存
    data_flow_data: Mapped[list | None] = mapped_column(JSONB)
    assist_trans_types: Mapped[list | None] = mapped_column(JSONB)  # 深度转化类型 Integer[]
    raw: Mapped[dict | None] = mapped_column(JSONB)

    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "package_id", name="uq_ocpc_packages_tenant_pkg"),
    )

    def bound_campaign_ids(self) -> list[int]:
        """scope 里绑定的计划 ID（level=2 计划级）。"""
        return [
            b.get("levelId")
            for b in (self.scope or [])
            if b.get("levelId") is not None
        ]

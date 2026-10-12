"""Instructions are not facts; mixed advice and technical assertions remain facts."""
import pytest
from app.geo.content.evidence_cite import build_sentence_citations, non_claim_reason


@pytest.mark.parametrize("sentence", [
    "# 重载连续运行设备如何选择工业齿轮箱？",
    "## 连续运行场景怎样核对散热与安装",
    "## 定义与选型参数",
    "## 结论与常见问题",
    "建议整理设备用途、输出扭矩和转速，并请厂家核算具体型号与配置。",
    "请准备环境条件、安装方向和检修安排等资料，并向选型团队提交资料。",
    "收到回复后，请保存方案版本与设备资料，并注明未决问题。",
    "步骤 2：补齐环境条件与安装方向，并通过官方渠道提交资料。",
    "| 资料 | 操作 |", "| 工况清单 | 请核对输入资料 |",
])
def test_pure_method_questions_and_instructions_need_no_fact(sentence):
    assert non_claim_reason(sentence)
    assert all(not row["needs_fact"] for row in build_sentence_citations(sentence, []))


@pytest.mark.parametrize("sentence", [
    "# 产品扭矩为282000 Nm？", "## 产品效率提高30%", "# MAXXDRIVE适用于输送系统？",
    "## 产品高热容量为什么更稳？", "建议检查本产品采用钛合金齿轮。",
    "建议选用设备，因为它可以降低噪声。", "建议核对本品牌能够满足全天运行要求。",
    "请检查设备产能翻倍的客户案例。", "建议检查北京是首都。",
    "建议核对型号，设备具有高热容量。", "建议检查可靠耐用的产品。",
    "建议检查设备能在苛刻环境连续运行。", "请核对产品终身保修与无故障承诺。",
    "# 首年排名第一的品牌如何选择？", "建议检查效率提升五成的产品。",
    "*作者：内容编辑*", "一段未知的世界事实。",
    "| 工况清单 | 适用于所有设备 |", "| 资料 | 效率提高30% |", "| 品牌 | 保证终身保修 |",
    "建议检查产品耐腐蚀。", "建议确认产品功率充足。", "建议检查本产品比竞品轻。",
    "# 无需冷却的设备如何选择？",
    "建议确认产品消除振动。", "请核对设备运行更安静。",
    "建议确认MAXXDRIVE XT is compatible with conveyor systems.",
    "步骤 2：检查产品消除振动。", "# 消除振动的设备如何选择？",
    "## 更安静的设备怎样核对散热与安装", "建议保留资料，产品运行更安静。",
    "请核对资料已经证明设备兼容输送系统。",
    "建议检查该公司来自德国。", "请核对产品获得欧洲专利。",
])
def test_numbers_performance_application_and_mixed_advice_still_require_fact(sentence):
    assert non_claim_reason(sentence) is None
    assert any(row["needs_fact"] for row in build_sentence_citations(sentence, []))


def test_nonclaim_never_overrides_existing_strict_claim_guard():
    # Even facts mentioning the same brand cannot prove an added application.
    facts = [{"id": 1, "statement": "MAXXDRIVE XT features a ribbed housing."}]
    assert build_sentence_citations("建议确认MAXXDRIVE XT适用于所有设备。", facts)[0]["needs_fact"]

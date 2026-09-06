"""Historical scan regressions; synthetic examples, no customer data."""
import pytest
from app.geo.content.claim_guard import ungrounded_claims


def hits(body, statement='产品采用散热壳体。'):
    return ungrounded_claims(body,[{'id':1,'statement':statement,'title':'资料','source_name':'已核验资料'}])


@pytest.mark.parametrize('text',[
 '比如仅收到型号名称，还不能判断安装和维护条件是否已经沟通过。',
 '产品不适用于矿业。',
 '产品仅在室内适用于矿业。',
 '产品适用于矿业，但必须另配冷却系统。',
])
def test_preserves_exact_statement_or_nonassertive_example(text):
    assert not hits(text,text)


def test_advice_example_needs_no_product_evidence():
    assert not hits('比如仅收到型号名称，还不能判断安装和维护条件是否已经沟通过。')


@pytest.mark.parametrize('body,source',[
 ('产品适用于矿业。','产品不适用于矿业。'),
 ('产品适用于矿业。','产品仅在室内适用于矿业。'),
 ('产品适用于矿业。','产品适用于矿业，但必须配备冷却系统。'),
 ('产品适用于矿业。产品让寿命翻番。','产品适用于矿业。'),
])
def test_exact_source_exception_never_covers_other_claims(body,source):
    assert hits(body,source)


def test_sql_literal_only_exception():
    assert not hits("SELECT * FROM examples WHERE code LIKE '%1234567%'")
    assert hits("SELECT * FROM examples WHERE code LIKE '%1234567%'; 覆盖90%客户。")


@pytest.mark.parametrize('body,source',[
 ('最大输出扭矩为500000 Nm。','最大输出扭矩为15000 Nm。'),
 ('输出功率为15 kW。','输出扭矩为15 Nm。'),
 ('输出功率为15 W。','输出功率为15 kW。'),
 ('输出扭矩为15,000–500,000 Nm。','输出扭矩为15,000 Nm至282,000 Nm。'),
 ('该产品能够胜任港口重载作业。','产品采用散热壳体。'),
 ('该设计让密封寿命翻番。','产品采用散热壳体。'),
])
def test_engineering_or_paraphrased_assertion_requires_evidence(body,source):
    assert hits(body,source)


@pytest.mark.parametrize('body,source',[
 ('输出扭矩为15,000–282,000 Nm。','output torque from 15,000 Nm to 282,000 Nm'),
 ('输出扭矩为15000 N·m。','输出扭矩为15,000 Nm。'),
 ('功率为15.0 kW。','功率为15 kW。'),
 ('温度为40℃。','温度为40 °C。'),
])
def test_equivalent_quantity_notation(body,source):
    assert not hits(body,source)

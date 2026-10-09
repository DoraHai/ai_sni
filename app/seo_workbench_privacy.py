"""Conservative text redaction at the supplier and answer boundaries, not a DLP guarantee."""
import re

REDACTED = '[敏感信息已隐藏]'
CREDENTIAL_LABEL = r'(?:[\w-]*(?:api[_-]?key|(?:access[_-]?|refresh[_-]?)?token|secret(?:[_-]?key)?|password|passwd|sessionid)|密码|口令|密钥|令牌)'
RULES = (
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)'),
    re.compile(r'(?i)\b(?:postgres(?:ql)?(?:\+asyncpg)?|mysql|redis)://[^\s/]+:[^\s/@]+@'),
    re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}'),
    re.compile(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b'),
    re.compile(r'\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{12,}\b'),
    re.compile(r'''["']?''' + CREDENTIAL_LABEL + r'''["']?\s*[:=：]\s*(["'])(?:(?!\1)[^\r\n])*\1''', re.I),
    re.compile(r'''["']?''' + CREDENTIAL_LABEL + r'''["']?\s*[:=：]\s*[^\s,，;；"'<>]+''', re.I),
    re.compile(r'(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])'),
    re.compile(r'(?<!\d)(?:\+?86[ -]?)?1[3-9](?:[ -]?\d){9}(?!\d)'),
    re.compile(r'(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)'),
)
BOUNDARY_REQUEST = re.compile(
    r'(?:查看|列出|导出|读取|调取|给我|显示|获取|查询).{0,20}(?:其他|其它|全部|所有|别的).{0,8}(?:客户|租户).{0,12}(?:数据|资料|稿件|记录|账号)'
    r'|(?:查看|列出|导出|读取|给我|显示|获取|查询).{0,20}(?:系统提示词|API\s*Key|api[_-]?key|密钥|登录密码|访问令牌|数据库密码)', re.I)
OUT_OF_SCOPE = '我可以帮助你分析当前客户的网站、SEO、推广策略和稿件。请围绕当前工作空间的业务提问；其他客户资料和系统内部信息不在可访问范围。'


def redact_text(value):
    for rule in RULES:
        value = rule.sub(REDACTED, value)
    # Payment card candidates must satisfy Luhn, reducing false matches on ordinary numbers.
    def card(match):
        digits = re.sub(r'\D', '', match.group())
        checksum = sum((int(n) if i % 2 == 0 else (int(n) * 2 // 10 + int(n) * 2 % 10))
                       for i, n in enumerate(reversed(digits)))
        return REDACTED if checksum % 10 == 0 else match.group()
    return re.sub(r'(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)', card, value)


def redact(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value

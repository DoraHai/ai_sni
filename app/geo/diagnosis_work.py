"""Read-only implementation context for an existing diagnosis ticket."""
from urllib.parse import urlsplit
from fastapi import HTTPException

TECHNICAL = {'robots', 'https', 'canonical', 'indexable', 'schema', 'entity_schema', 'llms', 'language'}


def diagnosis_work_plan(ticket, audit):
    if (audit is None or ticket.audit_id != audit.id or ticket.tenant_id != audit.tenant_id
            or (ticket.advice_code or '').startswith(('workqueue:v1:', 'cockpit:v1:'))):
        raise HTTPException(404, '当前客户的诊断整改任务不存在')
    finding = next((f for f in (audit.findings or []) if isinstance(f, dict) and f.get('code') == ticket.advice_code), {})
    baseline = ticket.baseline_snapshot if isinstance(ticket.baseline_snapshot, dict) else {}
    url = audit.final_url or audit.url or ''
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            url = None
    except ValueError:
        url = None
    action = ticket.action or finding.get('recommendation') or '对照原始诊断和验收要求，明确需要修改的内容。'
    technical = ticket.advice_code in TECHNICAL
    acceptance = ticket.acceptance_desc or '核对实际页面与本次整改要求。'
    steps = [
        '打开目标页面，核对页面地址和原始问题；诊断是历史快照，当前情况可能已经变化。',
        ('由网站维护人员在网站配置或页面模板中执行：' if technical else '由内容编辑在对应页面的内容编辑器中执行：') + action,
        '保存并实际应用到网站，记录修改位置和内容；涉及文案发布时由客户审核一次。',
        ('回到此工单点击重抓验收，以实际抓取结果判断是否解决。' if ticket.acceptance_type == 'auto'
         else '保留实际页面链接和修改依据，再按人工验收要求记录结论。'),
    ]
    return dict(ticket_id=ticket.id, audit_id=audit.id, page_url=url,
                diagnosed_at=audit.created_at.isoformat() if audit.created_at else None,
                page_title=audit.page_title, source_code=ticket.advice_code,
                source_evidence=baseline.get('evidence', finding.get('evidence')),
                source_passed=baseline.get('passed', finding.get('passed')),
                suggested_role='网站维护人员' if technical else '内容编辑',
                action=action, steps=steps, acceptance=acceptance,
                acceptance_type=ticket.acceptance_type, acceptance_check=ticket.acceptance_check,
                outcome_note='页面整改通过不等于 AI 可见度提升；效果变化须通过指标验收任务验证。')

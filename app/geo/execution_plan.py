"""Turn persisted GEO work into concrete next steps and selectable evidence."""
import re
from collections import Counter

from app.geo.work_execution import freeze_samples
from app.geo.content.source_opportunities import source_url


def acceptance_blockers(plan):
    """Fail closed if any execution prerequisite is missing from the plan."""
    required = {'baseline', 'content', 'materials', 'article', 'publication', 'retest', 'comparison'}
    steps = {step['id']: step for step in plan.get('steps', [])}
    if required - steps.keys():
        return ['执行进度不完整，请刷新后重试']
    return [steps[key]['title'] for key in sorted(required) if not steps[key].get('done')]


def ticket_prompt_id(ticket):
    match = re.fullmatch(r'workqueue:v1:prompt-(\d+)', ticket.advice_code or '')
    return int(match[1]) if match else None


def candidates(rows):
    items, excluded = [], 0
    for row in rows:
        try:
            frozen = freeze_samples([row])[0]
        except ValueError:
            excluded += 1
            continue
        items.append({**frozen, 'raw_text': frozen['raw_text'][:500] if frozen['raw_text'] else ''})
    return items, excluded


def sample_gaps(before, after):
    b, a = Counter(r['engine'] for r in before), Counter(r['engine'] for r in after)
    return [dict(engine=e, before_count=b[e], after_count=a[e],
                 before_needed=max(0, 3-b[e]), after_needed=max(0, 3-a[e])) for e in sorted(b.keys() | a.keys())]


def execution_steps(ticket, task, article, fact_count, brief_ready, publications):
    baseline = ticket.baseline_snapshot or {}
    progress = ticket.progress or {}
    current = bool(task and article and ticket.content_task_id == task.id
                   and baseline.get('prompt_id') == task.prompt_id and progress.get('article_id') == article.id)
    saved_before = bool(task and ticket.content_task_id == task.id and baseline.get('prompt_id') == task.prompt_id and baseline.get('samples'))
    definitions = [
        ('baseline', '保留修改前证据', saved_before, '勾选同题真实样本，保存为修改前证据。'),
        ('content', '准备内容任务', bool(task), '直接创建或关联这个问题的内容任务，保留待办要求。'),
        ('materials', '补齐创作要求与事实', bool(brief_ready and fact_count >= 3), f'已绑定 {fact_count} 条可生成事实；确认创作要求并至少绑定 3 条。'),
        ('article', '完成内容修改', bool(article), '在编辑器补充事实、出处和适用条件，保存新版本并检查。'),
        ('publication', '完成发布回填', any(source_url(getattr(p, 'published_url', '') or '') for p in publications), '核对实际发布页面，在内容任务中回填当前版本的有效 HTTP(S) 发布地址。'),
        ('retest', '完成同题复测', bool(current and progress.get('samples')), '发布或保存修改后，用同一问题、同一引擎采样并关联。'),
        ('comparison', '核验前后变化', bool(current and (progress.get('comparison') or {}).get('comparable')), '前后每个引擎至少 3 条样本，核对差异后再人工验收。'),
    ]
    steps = [dict(id=id, title=title, done=done, instruction=instruction) for id, title, done, instruction in definitions]
    next_step = next((s['id'] for s in steps if not s['done']), 'acceptance')
    return steps, next_step

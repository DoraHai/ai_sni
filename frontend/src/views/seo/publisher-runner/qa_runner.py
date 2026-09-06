"""Visible, operator-directed answer filling. Never clicks save or publish."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import urlparse
from runner import allowed_frame, fill_empty

HOSTS = {'zhihu':'www.zhihu.com','csdn_qa':'ask.csdn.net'}


def validate_task(task):
    if not isinstance(task,dict) or task.get('kind')!='seo_qa_assist' or task.get('schema_version')!=1:
        raise ValueError('不是问答填稿任务')
    for key in ['tenant_id','site_id','placement_id','content_version']:
        if type(task.get(key)) is not int or task[key]<=0: raise ValueError('任务编号或版本无效')
    platform=task.get('platform')
    if platform not in HOSTS: raise ValueError('仅支持知乎与 CSDN 问答')
    url=urlparse(task.get('question_url',''))
    pattern=r'/question/\d+' if platform=='zhihu' else r'/questions/\d+/?'
    if url.scheme!='https' or url.hostname!=HOSTS[platform] or url.username or url.password or url.port or url.query or url.fragment or not re.fullmatch(pattern,url.path):
        raise ValueError('任务必须指向对应平台的指定问题页')
    body=task.get('body')
    if not isinstance(body,str) or not body.strip() or len(body)>200000: raise ValueError('回答正文无效')
    expires=datetime.fromisoformat(task.get('expires_at','').replace('Z','+00:00'))
    if expires.tzinfo is None or expires<=datetime.now(timezone.utc): raise ValueError('任务已过期，请从工作台重新下载')
    return task


def prepare_answer(page,task):
    validate_task(task)
    actual,expected=urlparse(page.url),urlparse(task['question_url'])
    if actual.scheme!='https' or actual.hostname!=expected.hostname or actual.username or actual.password or actual.port or actual.path.rstrip('/')!=expected.path.rstrip('/'):
        raise ValueError('当前页面不是任务指定的问题，未填稿')
    candidates=[]
    for frame in page.frames:
        if not allowed_frame(frame,expected.hostname): continue
        active=frame.locator('textarea:focus,[contenteditable="true"]:focus')
        for element in active.all():
            if element.is_visible() and element.is_enabled(): candidates.append(element)
    if len(candidates)!=1: raise ValueError('请先点击唯一的回答正文编辑区，不要选评论框')
    element=candidates[0]
    label=' '.join(element.get_attribute(k) or '' for k in ['placeholder','aria-label','name','id','class'])
    if re.search(r'评论|comment|标题|title|search|搜索',label,re.I): raise ValueError('选中的是评论、标题或搜索框，未填稿')
    fill_empty(element,task['body'])
    return '已填入审核正文，请人工检查并自行发布；发布后回工作台回填网址。'


def make_receipt(task, answer_url):
    # A receipt is an operator report, never proof of publication.
    if type(task.get('version')) is not int or task['version'] <= 0:
        raise ValueError('旧任务不支持回执，请在工作台手动回填网址')
    actual, expected = urlparse(answer_url.strip()), urlparse(task['question_url'])
    question_path = expected.path.rstrip('/')
    valid_path = (bool(re.fullmatch(re.escape(question_path) + r'/answer/\d+/?', actual.path))
                  if task['platform'] == 'zhihu' else actual.path.rstrip('/') == question_path)
    if (actual.scheme != 'https' or actual.hostname != expected.hostname or actual.username or
            actual.password or actual.port or not valid_path or len(answer_url) > 2000):
        raise ValueError('回答网址必须属于当前平台的指定问题，不接受编辑页')
    return {**{key: task[key] for key in ['tenant_id','site_id','placement_id','version',
            'content_version','platform','question_url']}, 'kind':'seo_qa_receipt','schema_version':1,
            'answer_url':actual._replace(query='').geturl()}


def collect_receipt(task, output):
    while True:
        value = input('发布后粘贴公开回答网址生成回执；尚未发布可直接回车跳过：').strip()
        if not value: return
        try:
            receipt = make_receipt(task, value)
        except ValueError as exc:
            print(str(exc)); continue
        with output.open('x', encoding='utf-8') as target:
            json.dump(receipt, target, ensure_ascii=False, indent=2)
        print('已生成 '+str(output)+'，请在工作台“回填网址”中导入并核验。此文件不是发布成功证明。')
        return


def main():
    parser=argparse.ArgumentParser(description='问答本地填稿助手：不点击保存或发布')
    parser.add_argument('task',type=Path)
    parser.add_argument('--account',required=True,help='本机账号标签，用于隔离浏览器登录目录')
    args=parser.parse_args()
    if not args.account.strip() or len(args.account)>200: raise ValueError('账号标签无效')
    if args.task.stat().st_size>1000000: raise ValueError('任务文件过大')
    task=validate_task(json.loads(args.task.read_text(encoding='utf-8-sig')))
    from playwright.sync_api import sync_playwright
    profile=hashlib.sha256((task['platform']+'|'+args.account).encode()).hexdigest()[:24]
    key=hashlib.sha256(json.dumps([task['tenant_id'],task['site_id'],task['placement_id'],task['content_version'],task['body'],args.account],ensure_ascii=False).encode()).hexdigest()
    root=Path.cwd()/'.qa-assistant';root.mkdir(exist_ok=True)
    journal=root/(key+'.json')
    if journal.exists(): raise ValueError('该账号已尝试此版填稿。请人工核对平台，不自动重复；需要重试时先确认无残留再处理本机记录。')
    with sync_playwright() as p:
        context=p.chromium.launch_persistent_context(str(root/profile),headless=False)
        try:
            page=context.pages[0] if context.pages else context.new_page()
            page.goto(task['question_url'],wait_until='domcontentloaded')
            input('请登录并核对账号 '+args.account+'，打开该问题的回答编辑器，点击正文输入区后回车：')
            validate_task(task)
            with journal.open('x',encoding='utf-8') as output:
                json.dump({'state':'fill_attempted','placement_id':task['placement_id']},output)
            print(prepare_answer(page,task))
            collect_receipt(task, Path.cwd()/('qa-receipt-'+key[:16]+'.json'))
        finally: context.close()


if __name__=='__main__':
    try: main()
    except (ValueError,OSError) as exc: raise SystemExit(str(exc))

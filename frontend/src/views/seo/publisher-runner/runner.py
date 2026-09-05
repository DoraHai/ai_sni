"""Local, visible browser executor. Login state never leaves this computer."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

PROFILES = {
    'baijiahao': {'host': 'baijiahao.baidu.com', 'public': ['baijiahao.baidu.com']},
    'toutiao': {'host': 'mp.toutiao.com', 'public': ['www.toutiao.com', 'toutiao.com']},
    'sohu': {'host': 'mp.sohu.com', 'public': ['www.sohu.com']},
}
TITLE = 'input[placeholder*="标题"],textarea[placeholder*="标题"],input[aria-label*="标题"],input[name="title"],input[placeholder*="title" i]'
BODY = 'textarea:not([placeholder*="标题"]),[contenteditable="true"],body[contenteditable=""]'


def validate_task(item):
    if not isinstance(item, dict) or item.get('platform_code') not in PROFILES:
        raise ValueError('本地执行器当前仅支持百家号、头条号、搜狐号')
    url = urlparse(item.get('editor_url', ''))
    if url.scheme != 'https' or url.hostname != PROFILES[item['platform_code']]['host'] or url.username or url.password or url.port:
        raise ValueError('编辑器必须使用对应平台的官方 HTTPS 地址')
    if type(item.get('publication_id')) is not int or item['publication_id'] <= 0:
        raise ValueError('任务 ID 无效')
    for key, maximum in [('title', 200), ('text', 200000), ('account', 200), ('source_version', 40)]:
        value = item.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError('任务字段无效：' + key)
    return item


def task_key(task):
    fields = {k: task[k] for k in ['publication_id', 'platform_code', 'account', 'source_version', 'title', 'text']}
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def public_url(value, platform):
    url = urlparse(value)
    if url.scheme != 'https' or url.hostname not in PROFILES[platform]['public'] or url.username or url.password or url.port or url.path in {'', '/'} or re.search(r'/editor|/write|/draft|/login', url.path):
        raise ValueError('请使用对应平台公开文章地址，不接受编辑器或登录页')
    return url._replace(fragment='').geturl()


def save_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def allowed_frame(frame, host):
    parsed = urlparse(frame.url)
    if parsed.scheme == 'https' and parsed.hostname == host and not parsed.port:
        return True
    if frame.url in {'about:blank', 'about:srcdoc'} and frame.parent_frame:
        sandbox = frame.frame_element().get_attribute('sandbox')
        if sandbox is not None and 'allow-same-origin' not in sandbox.split():
            return False
        return allowed_frame(frame.parent_frame, host)
    return False


def unique_visible(page, selector):
    matches = []
    for frame in page.frames:
        if not allowed_frame(frame, urlparse(page.url).hostname):
            continue
        for element in frame.locator(selector).all():
            if element.is_visible() and element.is_enabled():
                matches.append(element)
    if len(matches) != 1:
        raise ValueError('无法唯一识别编辑区，需要人工处理，未继续执行')
    return matches[0]


def accepts_images(accept, images):
    tokens = {token.strip().lower() for token in (accept or '').split(',')}
    mime = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
    return bool(images) and all(path.suffix.lower() in mime and (
        'image/*' in tokens or mime[path.suffix.lower()] in tokens or path.suffix.lower() in tokens
    ) for path in images)


def fill_empty(element, text):
    existing = element.evaluate('(el) => "value" in el ? el.value : el.innerText') or ''
    if existing.strip() == text.strip():
        return
    if existing.strip() or element.locator('img,video,iframe').count():
        raise ValueError('编辑区已有不同内容，未覆盖')
    maximum = element.get_attribute('maxlength')
    if maximum and int(maximum) > 0 and len(text) > int(maximum):
        raise ValueError('内容超过编辑器长度限制')
    element.fill(text)
    actual = element.evaluate('(el) => "value" in el ? el.value : el.innerText') or ''
    if actual.strip() != text.strip():
        raise ValueError('编辑器未保留完整文字，需要人工检查')


def prepare(page, task, images):
    validate_task(task)
    parsed = urlparse(page.url)
    if parsed.scheme != 'https' or parsed.hostname != PROFILES[task['platform_code']]['host'] or parsed.port:
        raise ValueError('当前页面不是对应平台的官方编辑器')
    # Resolve both fields before writing either; ambiguous forms remain untouched.
    title, body = unique_visible(page, TITLE), unique_visible(page, BODY)
    fill_empty(title, task['title'])
    fill_empty(body, task['text'])
    if images:
        inputs = [el for el in page.locator('input[type=file]').all() if el.is_enabled() and accepts_images(el.get_attribute('accept'), images)]
        if len(inputs) != 1 or (len(images) > 1 and inputs[0].get_attribute('multiple') is None):
            raise ValueError('无法唯一识别支持这些图片的上传入口，请在平台上传；文字已保留')
        inputs[0].set_input_files([str(path) for path in images])
        return '文字已填入，图片已交给上传控件；请核对平台是否上传完成及正文中的位置'
    return '文字已填入，请核对封面、图片、分类和声明'


def click_exact(page, labels):
    controls = [el for label in labels for el in page.get_by_role('button', name=label, exact=True).all() if el.is_visible() and el.is_enabled()]
    if len(controls) != 1:
        raise ValueError('无法唯一识别操作按钮，需要人工处理')
    controls[0].click(timeout=10000)


def editor_url(value, platform):
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.hostname != PROFILES[platform]['host'] or parsed.username or parsed.password or parsed.port:
        raise ValueError('草稿恢复地址必须属于对应平台官方编辑器')
    return value


def apply_settings(page, settings):
    """Use unambiguous, accessible controls; unknown layouts stop for intervention."""
    category = settings.get('category')
    if category:
        control = page.get_by_role('combobox', name=re.compile('分类|领域'))
        if control.count() != 1 or not control.is_visible():
            raise ValueError('未识别唯一分类控件，请在平台选择分类后继续')
        control.select_option(label=category)
    cover = settings.get('cover')
    if cover:
        path = Path(cover)
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {'.jpg','.jpeg','.png'} or path.stat().st_size > 3*1024*1024:
            raise ValueError('封面必须是本机 JPG/PNG 文件，最大 3 MB')
        control = page.get_by_label(re.compile('封面'))
        if control.count()!=1 or control.get_attribute('type')!='file' or not accepts_images(control.get_attribute('accept'),[path]):
            raise ValueError('未识别唯一封面上传入口，请在平台补充封面')
        control.set_input_files(str(path))
        # File selection is not upload completion. Require a loaded remote thumbnail.
        page.wait_for_function("() => [...document.images].some(i => /封面/.test(i.alt) && /^https:/.test(i.currentSrc) && i.complete && i.naturalWidth > 0)", timeout=30000)


def confirm_body_upload(page, task, count):
    if not count:return
    body=unique_visible(page,BODY)
    # Do not count local blob/data previews as completed server uploads.
    body.evaluate("""(el, count) => new Promise((resolve, reject) => {
      const ready=()=>[...el.querySelectorAll('img')].filter(i=>/^https:/.test(i.currentSrc)&&i.complete&&i.naturalWidth>0).length>=count;
      if(ready())return resolve(true);
      const started=Date.now(),timer=setInterval(()=>{if(ready()){clearInterval(timer);resolve(true)}
        else if(Date.now()-started>30000){clearInterval(timer);reject(new Error('图片尚未确认上传完成，请在平台核实'))}},250)
    })""",count)


def collect_result(page, task):
    """Match one article row by exact title; never infer from page-wide status text."""
    matches=page.get_by_role('row').filter(has=page.get_by_text(task['title'],exact=True))
    if matches.count()!=1:return {'state':'unknown'}
    row=matches.first
    states=[value for value in ['审核中','待审核','已发布','未通过','草稿'] if row.get_by_text(value,exact=True).count()==1]
    state=states[0] if len(states)==1 else 'unknown'
    links=[]
    if state=='已发布':
        for link in row.get_by_role('link').all():
            try:links.append(public_url(link.get_attribute('href') or '',task['platform_code']))
            except ValueError:pass
    return {'state':state,'page_url':links[0] if len(set(links))==1 else None}


def main():
    parser = argparse.ArgumentParser(description='国内平台本地执行器：可见浏览器、素材上传、草稿及授权提交')
    parser.add_argument('package', type=Path)
    parser.add_argument('--workdir', type=Path, default=Path.home() / 'GSnipersPublisher')
    parser.add_argument('--images', type=Path, help='图片目录，按任务 ID 分子目录；每篇最多 20 张 JPG/PNG')
    parser.add_argument('--publish', action='store_true', help='允许逐篇确认后点击发布；默认只填稿/保存草稿')
    parser.add_argument('--batch', action='store_true', help='展示全部任务并统一确认，只有异常需要介入')
    parser.add_argument('--settings', type=Path, help='可选 JSON，以任务 ID 为键指定 category、cover 和 editor_url')
    args = parser.parse_args()
    if args.images and not args.images.is_dir():
        raise ValueError('图片目录不存在')
    if args.package.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('任务包不能超过 20 MB')
    package = json.loads(args.package.read_text(encoding='utf-8-sig'))
    if package.get('schema') != 'seo-domestic-publisher-v1' or not isinstance(package.get('items'), list) or not 1 <= len(package['items']) <= 50:
        raise ValueError('请选择有效任务包（1–50 条）')
    tasks = [validate_task(item) for item in package['items']]
    args.recipes = {}
    if args.settings:
        if args.settings.stat().st_size>100000:raise ValueError('设置文件不能超过 100 KB')
        args.recipes=json.loads(args.settings.read_text(encoding='utf-8-sig'))
        if not isinstance(args.recipes,dict):raise ValueError('设置必须按任务 ID 组织')
        for task in tasks:
            setting=args.recipes.get(str(task['publication_id']),{})
            if not isinstance(setting,dict) or set(setting)-{'category','cover','editor_url'}:raise ValueError('不支持的任务设置')
            if setting.get('editor_url'):editor_url(setting['editor_url'],task['platform_code'])
    if args.batch:
        for task in tasks:print(task['publication_id'],task['platform_code'],task['account'],task['title'])
        print('本批操作：', '提交发布' if args.publish else '保存草稿', '。请核对全部账号、内容和素材；平台登录、声明或未知页面需要介入。')
        if input('输入 确认批次 开始：').strip()!='确认批次':return 0
    if len({t['publication_id'] for t in tasks}) != len(tasks):
        raise ValueError('任务 ID 重复')
    args.workdir.mkdir(parents=True, exist_ok=True)
    # Exclusive process lock: stale lock after a crash requires inspecting the journal first.
    lock = args.workdir / 'runner.lock'
    with lock.open('x', encoding='utf-8') as handle:
        handle.write('正在运行；异常退出后先核实平台发布记录，再删除此锁文件。')
    try:
        report = execute(args, tasks)
        return 1 if report['failed'] else 0
    finally:
        lock.unlink(missing_ok=True)


def execute(args, tasks):
    from playwright.sync_api import sync_playwright
    journal_path, results_path = args.workdir / 'journal.json', args.workdir / 'results.json'
    journal = json.loads(journal_path.read_text(encoding='utf-8')) if journal_path.exists() else {}
    results = json.loads(results_path.read_text(encoding='utf-8')) if results_path.exists() else {'schema': 'seo-domestic-results-v1', 'items': []}
    report = {'items': [], 'failed': 0, 'pending': 0, 'recorded': 0}
    def record_report():
        for state in ['failed', 'pending', 'recorded']:
            report[state] = sum(item['state'] == state for item in report['items'])
        save_json(args.workdir / 'run-report.json', report)
    with sync_playwright() as browser:
        for task in tasks:
            key = task_key(task)
            task_report = {'publication_id': task['publication_id'], 'state': 'pending'}
            report['items'].append(task_report)
            if journal.get(key, {}).get('state') == 'published_url_recorded':
                task_report['state'] = 'recorded'
                record_report()
                print('跳过已回收结果的任务', task['publication_id']);continue
            account = hashlib.sha256((task['platform_code'] + ':' + task['account']).encode()).hexdigest()[:24]
            context = None
            try:
                context = browser.chromium.launch_persistent_context(str(args.workdir / 'profiles' / account), headless=False)
                page = context.pages[0] if context.pages else context.new_page()
                previous = journal.get(key, {})
                settings=getattr(args,'recipes',{}).get(str(task['publication_id']),{})
                target=previous.get('draft_url') or settings.get('editor_url') or task['editor_url']
                page.goto(editor_url(target,task['platform_code']), wait_until='domcontentloaded', timeout=45000)
                if previous.get('state') in {'preparation_attempted', 'prepared', 'submit_attempted', 'needs_result_check','draft_save_attempted'}:
                    print('上次已开始处理，本次不会重复填稿、上传或提交。请到平台核实并完成剩余操作。')
                else:
                    print(f"任务 {task['publication_id']} / {task['account']} / {task['title']}")
                    if not getattr(args,'batch',False):input('请登录、确认账号并打开空白编辑器，完成后按 Enter：')
                    image_dir = args.images / str(task['publication_id']) if args.images else None
                    if image_dir and image_dir.is_symlink():
                        raise ValueError('不接受符号链接素材目录')
                    files = sorted(image_dir.glob('*')) if image_dir and previous.get('state')!='draft_saved' else []
                    if len(files) > 20 or any(not p.is_file() or p.is_symlink() or p.suffix.lower() not in {'.jpg', '.jpeg', '.png'} or p.stat().st_size > 3*1024*1024 for p in files) or sum(p.stat().st_size for p in files) > 12*1024*1024:
                        raise ValueError('每篇最多 20 张 JPG/PNG，每张 3 MB、合计 12 MB，不接受符号链接')
                    journal[key] = {'publication_id': task['publication_id'], 'state': 'preparation_attempted'}
                    save_json(journal_path, journal)
                    print(prepare(page, task, files))
                    if getattr(args,'batch',False):
                        confirm_body_upload(page,task,len(files))
                        if previous.get('state')!='draft_saved':apply_settings(page,settings)
                    journal[key] = {'publication_id': task['publication_id'], 'state': 'prepared'}
                    save_json(journal_path, journal)
                    action = ('publish' if args.publish else 'draft') if getattr(args,'batch',False) else input('请在平台核对素材、封面、分类和声明。输入 draft 保存草稿，publish 提交，其他跳过操作：').strip()
                    current = urlparse(page.url)
                    if current.scheme != 'https' or current.hostname != PROFILES[task['platform_code']]['host'] or current.port:
                        raise ValueError('页面已离开对应平台，未执行保存或发布')
                    if action == 'draft':
                        journal[key]['state']='draft_save_attempted';save_json(journal_path,journal)
                        click_exact(page, ['保存草稿', '存草稿'])
                        if getattr(args,'batch',False):
                            page.get_by_text(re.compile('^(保存成功|草稿已保存)$')).wait_for(timeout=15000)
                            saved=editor_url(page.url,task['platform_code'])
                            if urlparse(saved).path not in {'','/'}:
                                journal[key].update(state='draft_saved',draft_url=saved);save_json(journal_path,journal)
                        print('已点击保存草稿，请核对平台保存结果。')
                    elif action == 'publish' and args.publish:
                        journal[key]['state'] = 'submit_attempted'
                        save_json(journal_path, journal)  # Write before click, including uncertain timeouts.
                        click_exact(page, ['发布', '发表'])
                        journal[key]['state'] = 'needs_result_check'
                        save_json(journal_path, journal)
                        print('已提交操作，请处理平台确认/审核；尚未判定发布成功。')
                    elif action == 'publish':
                        print('未启用 --publish，请在平台手动发布。')
                observed=collect_result(page,task) if getattr(args,'batch',False) else {}
                task_report['platform_state']=observed.get('state','unknown')
                value = observed.get('page_url') or ('' if getattr(args,'batch',False) else input('平台确认发布后粘贴公开文章链接，留空保留待核实状态：').strip())
                if value:
                    value = public_url(value, task['platform_code'])
                    results['items'] = [r for r in results['items'] if r['publication_id'] != task['publication_id']]
                    results['items'].append({k: task[k] for k in ['publication_id', 'platform_code', 'source_version'] } | {'page_url': value})
                    save_json(results_path, results)
                    journal[key] = {'publication_id': task['publication_id'], 'state': 'published_url_recorded', 'page_url': value}
                    save_json(journal_path, journal)
                    task_report['state'] = 'recorded'
            except Exception as exc:
                task_report.update(state='failed', error=type(exc).__name__)
                print('已暂停当前任务：', type(exc).__name__, str(exc)[:300])
                print('已保留执行记录；请核对平台后继续。')
            finally:
                if context is not None:
                    try:
                        context.close()
                    except Exception as exc:
                        task_report.update(state='failed', error='browser_close_' + type(exc).__name__)
                record_report()
    print(f"本批处理：已记录链接 {report['recorded']}，待人工处理 {report['pending']}，失败 {report['failed']}。详见 run-report.json。")
    if results_path.exists():
        print('结果文件：', results_path, '，请在分发工作台回收。登录状态只保存在本机 profiles 目录。')
    return report


if __name__ == '__main__':
    raise SystemExit(main())

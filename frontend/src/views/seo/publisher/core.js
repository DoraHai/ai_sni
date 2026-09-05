export const platformHosts = Object.freeze({
  baijiahao: ['baijiahao.baidu.com'], toutiao: ['mp.toutiao.com'], sohu: ['mp.sohu.com'],
  wangyi: ['mp.163.com'], penguin: ['om.qq.com'], wechat_browser: ['mp.weixin.qq.com'],
  xiaohongshu: ['creator.xiaohongshu.com'], weibo: ['weibo.com'], zhihu: ['zhuanlan.zhihu.com'],
  csdn: ['editor.csdn.net'], juejin: ['juejin.cn'], jianshu: ['www.jianshu.com'],
})

export function validatePackage(value) {
  if (value?.schema !== 'seo-domestic-publisher-v1' || !Array.isArray(value.items) || !value.items.length || value.items.length > 50) throw new Error('请选择有效的填稿任务包（1–50 条）')
  const seen = new Set()
  const items = value.items.map(item => {
    if (!item || !platformHosts[item.platform_code] || typeof item.title !== 'string' || !item.title.trim() || item.title.length > 200 || typeof item.text !== 'string' || !item.text.trim() || item.text.length > 200000) throw new Error('任务内容不完整或超出限制')
    const url = new URL(item.editor_url)
    if (url.protocol !== 'https:' || url.username || url.password || !platformHosts[item.platform_code].includes(url.hostname) || url.port) throw new Error('任务包的编辑器地址不属于对应官方平台')
    if (!Number.isSafeInteger(item.publication_id) || item.publication_id <= 0 || seen.has(item.publication_id)) throw new Error('任务 ID 无效或重复')
    if (typeof item.account !== 'string' || !item.account.trim() || item.account.length > 200) throw new Error('任务缺少账号标识')
    seen.add(item.publication_id)
    return { publication_id: item.publication_id, platform_code: item.platform_code, account: item.account,
      title: item.title, text: item.text, editor_url: url.href, source_version: String(item.source_version || '').slice(0,40) }
  })
  return { schema: value.schema, items }
}

// Runs as a serialized function in the active tab: no imports, network, or submit clicks.
export function fillField(field, text, allowedHosts) {
  if (location.protocol !== 'https:' || !allowedHosts.includes(location.hostname) || location.port) return { ok: false, message: '当前页面不是该任务的官方平台' }
  if (!['title', 'body'].includes(field) || typeof text !== 'string' || !text.trim()) return { ok: false, message: '填稿内容无效' }
  const visible = el => el.getClientRects().length && !el.disabled && !el.readOnly && getComputedStyle(el).visibility !== 'hidden'
  const docs = [document]
  for (const frame of document.querySelectorAll('iframe')) {
    try { if (visible(frame) && frame.contentDocument) docs.push(frame.contentDocument) } catch { /* cross-origin frames are left untouched */ }
  }
  const titleHint = el => /标题|title/i.test([el.getAttribute('placeholder'), el.getAttribute('aria-label'), el.getAttribute('data-placeholder'), el.name, el.id].filter(Boolean).join(' '))
  const candidates = docs.flatMap(doc => [...doc.querySelectorAll('input[type="text"],input:not([type]),textarea,[contenteditable="true"],body[contenteditable=""]')])
    .filter(visible).filter(el => field === 'title' ? titleHint(el) : !titleHint(el) && (el.tagName === 'TEXTAREA' || el.isContentEditable || el.getAttribute('contenteditable') === 'true' || el.tagName === 'BODY'))
    .filter((el, _, all) => !all.some(other => other !== el && other.contains(el)))
  const focused = candidates.filter(el => el.ownerDocument.activeElement === el)
  const target = focused.length === 1 ? focused[0] : candidates.length === 1 ? candidates[0] : null
  if (!target) return { ok: false, message: '未能唯一识别编辑区。请先点选标题或正文编辑框，再打开助手；仍无法识别时使用复制粘贴。' }
  const existing = 'value' in target ? target.value : target.textContent
  if ((existing || '').trim() || target.querySelector('img,video,iframe')) return { ok: false, message: '编辑框已有内容，已停止填入，避免覆盖；请自行核对后处理' }
  if ('maxLength' in target && target.maxLength > 0 && text.length > target.maxLength) return { ok: false, message: '内容超过平台编辑框长度限制，请先修改专属稿' }
  target.focus()
  if ('value' in target) {
    const proto = target.tagName === 'TEXTAREA' ? target.ownerDocument.defaultView.HTMLTextAreaElement.prototype : target.ownerDocument.defaultView.HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(target, text)
  } else {
    const doc = target.ownerDocument
    const range = doc.createRange(); range.selectNodeContents(target)
    const selection = doc.defaultView.getSelection(); selection.removeAllRanges(); selection.addRange(range)
    if (!doc.execCommand('insertText', false, text)) return { ok: false, message: '平台编辑器不接受自动填入，请使用复制粘贴' }
  }
  const view = target.ownerDocument.defaultView
  target.dispatchEvent(new view.Event('input', { bubbles: true }))
  target.dispatchEvent(new view.Event('change', { bubbles: true }))
  const actual = 'value' in target ? target.value : target.textContent
  if (!(actual || '').trim()) return { ok: false, message: '未检测到已填入文字，请使用复制粘贴' }
  return { ok: true, message: '已填入文字，请核对平台是否保留内容，再检查配图、排版和声明并自行保存。尚未发布。' }
}

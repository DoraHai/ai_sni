import { validatePackage, platformHosts, fillField } from './core.js'
const $ = id => document.getElementById(id)
let pack = { items: [] }
let busy = false
const current = () => pack.items[Number($('tasks').value)]
const status = message => { $('status').textContent = message }
function render() {
  $('tasks').replaceChildren(...pack.items.map((item, i) => new Option(`${item.account} · ${item.title}`, i)))
  $('account').checked = false
  describe()
}
function describe() {
  $('account').checked = false
  const item = current()
  $('meta').textContent = item ? `任务 #${item.publication_id} / 原稿版本 ${item.source_version} / ${item.text.length} 字` : '暂无任务'
  for (const id of ['open','title','body','copyTitle','copyBody']) $(id).disabled = !item
}
$('tasks').onchange = describe
$('file').onchange = async event => {
  try {
    const file = event.target.files[0]
    if (!file || file.size > 2 * 1024 * 1024) throw new Error('任务包不得超过 2 MB')
    const next = validatePackage(JSON.parse(await file.text()))
    await chrome.storage.session.set({ seoDrafts: next })
    pack = next; render(); status(`已导入 ${pack.items.length} 条任务，请核对当前账号`)
  } catch (error) { status(error.message) }
  finally { event.target.value = '' }
}
async function run(action) {
  if (busy) return
  busy = true
  try { await action() } catch (error) { status(error.message) } finally { busy = false }
}
$('open').onclick = () => run(async () => {
  if (!current()) return
  await chrome.tabs.create({ url: current().editor_url })
  status('进入编辑器后，请在该页面再次打开助手并核对账号')
})
for (const field of ['title','body']) $(field).onclick = () => run(async () => {
  const item = current()
  if (!item || !$('account').checked) throw new Error('请先核对平台当前登录账号并勾选确认')
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  const results = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: fillField,
    args: [field, field === 'title' ? item.title : item.text, platformHosts[item.platform_code]] })
  status(results[0]?.result?.message || '未获得填稿结果，请在平台核对')
})
for (const [id,field] of [['copyTitle','title'],['copyBody','text']]) $(id).onclick = () => run(async () => {
  if (!current()) return
  await navigator.clipboard.writeText(current()[field]); status('已复制，可在官方编辑器粘贴')
})
$('clear').onclick = () => run(async () => { await chrome.storage.session.remove('seoDrafts'); pack = { items: [] }; render(); status('本次浏览器会话中的任务已清除') })
try {
  const { seoDrafts } = await chrome.storage.session.get('seoDrafts')
  if (seoDrafts) pack = validatePackage(seoDrafts)
  render()
} catch (error) { render(); status(error.message) }

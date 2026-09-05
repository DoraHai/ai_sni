import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { JSDOM } from 'jsdom'
import { SEM_PLANNED_CHANNELS, semChannelPath } from '../src/constants/semChannels.js'

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), 'utf8')
assert.deepEqual(SEM_PLANNED_CHANNELS.map((c) => c.id), ['bing', '360', 'soso'])
assert.equal(new Set(SEM_PLANNED_CHANNELS.map((c) => semChannelPath(c.id))).size, 3)
for (const channel of SEM_PLANNED_CHANNELS) {
  assert.equal(Object.isFrozen(channel), true)
  assert.match(semChannelPath(channel.id), /^\/sem\/channels\/(bing|360|soso)$/)
  assert.ok(channel.description)
}
assert.equal(SEM_PLANNED_CHANNELS[2].subtitle, '平台待确认')
const app = await source('src/App.vue')
const router = await source('src/router/index.js')
const view = await source('src/views/manage/SemChannelComingSoonView.vue')
assert.match(app, /label: '广告渠道'/)
assert.match(app, /SEM_PLANNED_CHANNELS\.map/)
assert.match(router, /SEM_PLANNED_CHANNELS\.map/)
assert.match(router, /perm: 'sem.assets', semChannelReservation: true/)
assert.match(router, /props: \{ channel \}/)
assert.match(app, /!route\.meta\.semChannelReservation[\s\S]*!route\.path\.startsWith\('\/seo'\)/)
assert.match(app, /tenantModuleScope === 'sem' && !route\.meta\.semChannelReservation/)
assert.match(view, /不会展示百度数据/)
assert.match(view, /不会自动继承百度账户授权或真实回写权限/)
assert.doesNotMatch(view, /fetch\(|axios|client\.|localStorage|session\.|@click|<button|<el-button|from .*api/)
// Existing SEM account navigation remains in place, alongside the new reservations.
assert.match(app, /label: '推广账号', path: '\/sem\/accounts', key: 'sem.assets'/)
assert.equal([...app.matchAll(/path: '\/sem\/accounts'/g)].length, 1, 'Do not duplicate the existing account menu')

// Compile and render the actual Vue component, not just source string checks.
// Middleware mode opens no listening port; there is no production API or login.
const server = await createServer({
  configFile: false,
  root: fileURLToPath(new URL('../', import.meta.url)),
  plugins: [vue()],
  server: { middlewareMode: true },
  appType: 'custom',
})
try {
  const { default: Component } = await server.ssrLoadModule('/src/views/manage/SemChannelComingSoonView.vue')
  for (const channel of SEM_PLANNED_CHANNELS) {
    const html = await renderToString(createSSRApp(Component, { channel }))
    const dom = new JSDOM(html)
    const doc = dom.window.document
    assert.equal(doc.querySelector('h1').textContent, channel.name)
    assert.equal(doc.querySelector('.status').textContent, '待开放')
    assert.equal(doc.querySelectorAll('.capabilities li').length, 4)
    assert.equal(doc.querySelectorAll('button, input, form, iframe, a[href]').length, 0)
    assert.ok(doc.querySelector('[role="note"]').textContent.includes('不会展示百度数据'))
    dom.window.close()
  }
} finally {
  await server.close()
}
console.log('SEM channel reservations: passed (static, permission-guarded, no integration actions)')

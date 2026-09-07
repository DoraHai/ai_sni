const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { JSDOM } = require('jsdom')
const { parse, compileScript } = require('@vue/compiler-sfc')
const dom = new JSDOM('<div id="app"></div>')
for (const key of ['window', 'document', 'Node', 'Element', 'HTMLElement', 'SVGElement']) global[key] = dom.window[key]
dom.window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
dom.window.HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
const { createApp, h, reactive, nextTick } = require('vue')
const filename = path.join(__dirname, '../src/views/workspace/cockpit/MetricEvidenceCard.vue')
const { descriptor } = parse(fs.readFileSync(filename, 'utf8'), { filename })
const compiled = compileScript(descriptor, { id: 'evidence-test', inlineTemplate: true }).content
  .replace(/import\s*\{([^}]+)\}\s*from\s*['"]vue['"];?/g, (_, names) => `const {${names.replace(/\bas\b/g, ':')}} = require('vue');`)
  .replace('export default', 'return')
const Component = new Function('require', compiled)(require)

async function main() {
  const props = reactive({ contextRevision: 1, metric: { contextRevision: 1, id: 'old', state: 'available',
    label: 'PRIVATE CUSTOMER A', display: '12345', series: [{ label: 'old-period', value: 8 }],
    columns: [{ key: 'secret', label: 'Details' }], rows: [{ secret: 'PRIVATE ROW' }] } })
  const events = []
  const app = createApp({ render: () => h(Component, { ...props, onDiscuss: value => events.push(value) }) })
  app.mount('#app')
  assert.ok(document.body.textContent.includes('PRIVATE CUSTOMER A'))
  const dialog = document.querySelector('dialog')
  assert.ok(document.getElementById(dialog.getAttribute('aria-labelledby')))
  document.querySelector('.metric-trigger').click()
  assert.ok(dialog.hasAttribute('open'))
  props.contextRevision = 2
  await nextTick()
  assert.equal(dialog.hasAttribute('open'), false)
  for (const text of ['PRIVATE CUSTOMER A', '12345', 'PRIVATE ROW', 'old-period']) {
    assert.equal(document.body.textContent.includes(text), false, `stale ${text}`)
  }
  assert.equal(document.querySelectorAll('.trend-point').length, 0)
  document.querySelector('.card-footer button').click()
  assert.equal(events.length, 0)
  props.metric = { contextRevision: 2, id: 'new', state: 'available', label: 'Current', display: '0',
    series: [{ label: 'a', value: 0 }, { label: 'b', value: null }, { label: 'c', value: 4 }] }
  await nextTick()
  assert.equal(document.querySelectorAll('.trend-point').length, 2)
  assert.equal(document.querySelectorAll('.trend-line').length, 2)
  document.querySelector('.card-footer button').click()
  assert.deepEqual(events, [{ metricId: 'new', contextRevision: 2 }])
  app.unmount()
  console.log('Evidence card mount: stale data, dialog name, gaps, zero and discussion reference passed')
}
main().catch(error => { console.error(error); process.exitCode = 1 })

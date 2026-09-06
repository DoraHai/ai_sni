import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { createEditorContext } from '../src/utils/geoEditorContext.js'

const { parse } = createRequire(import.meta.url)('@babel/parser')
const file = readFileSync(new URL('../src/views/geo/GeoTaskEditorView.vue', import.meta.url), 'utf8')
const script = file.slice(file.indexOf('\n') + 1, file.indexOf('</script>'))
const node = parse(script, { sourceType: 'module' }).program.body.find(n => n.type === 'FunctionDeclaration' && n.id.name === 'exportCurrentVariant')
const handler = script.slice(node.start, node.end)

function setup() {
  const calls = []
  const values = {
    tenantId: { value: 1 }, taskId: { value: 14 }, docTab: { value: 'website' },
    task: { value: { variants: [{ channel: 'website', export_revision: 'a'.repeat(64) }] } },
    reviewDraftChanged: { value: false }, busy: { value: '' }, variantEdit: {}, variantViewMode: { value: '' },
    ElMessage: { warning: message => calls.push(['warning', message]), success: message => calls.push(['success', message]) },
    toastError: () => calls.push(['error']), load: async () => calls.push(['load']),
    applyVariantFromTask: () => calls.push(['apply']),
    exportGeoVariant: async (...args) => { calls.push(['api', ...args]); return { export_format: 'html', channel: 'website', body_html: '<p>Fixture</p>' } },
  }
  values.captureEditorContext = () => createEditorContext(() => [values.tenantId.value, values.taskId.value, 0, false])
  const context = vm.createContext(values)
  vm.runInContext(handler, context)
  return { context, calls }
}

test('explicit export uses the saved revision and does not approve or publish', async () => {
  const { context, calls } = setup()
  await context.exportCurrentVariant()
  assert.deepEqual(calls.find(c => c[0] === 'api'), ['api', 1, 14, 'website', 'a'.repeat(64)])
  assert.equal(context.variantEdit.body_html, '<p>Fixture</p>')
  assert.match(calls.find(c => c[0] === 'success')[1], /仍需通过客户审核/)
})

test('unsaved content or missing revision does not start export', async () => {
  for (const kind of ['unsaved', 'revision']) {
    const { context, calls } = setup()
    if (kind === 'unsaved') context.reviewDraftChanged.value = true
    else context.task.value.variants[0].export_revision = null
    assert.equal(await context.exportCurrentVariant(), false)
    assert.equal(calls.some(c => c[0] === 'api'), false)
    assert.equal(context.busy.value, '')
  }
})

test('late export response cannot refresh or overwrite another customer', async () => {
  const { context, calls } = setup()
  let resolve
  context.exportGeoVariant = () => new Promise(done => { resolve = done })
  const pending = context.exportCurrentVariant()
  context.tenantId.value = 2
  context.taskId.value = 20
  context.busy.value = 'new-task'
  resolve({ body_html: '<p>Old</p>' })
  assert.equal(await pending, false)
  assert.equal(calls.length, 0)
  assert.equal(context.variantEdit.body_html, undefined)
  assert.equal(context.busy.value, 'new-task')
})

test('Vue API adapter sends POST with a revision, with no implicit preview or generation', async () => {
  const source = readFileSync(new URL('../src/api/geoContent.js', import.meta.url), 'utf8')
  const entry = parse(source, { sourceType: 'module' }).program.body.find(n => n.type === 'ExportNamedDeclaration' && n.declaration?.id?.name === 'exportGeoVariant').declaration
  const calls = []
  const context = vm.createContext({ client: { post: (...args) => { calls.push(args); return Promise.resolve({}) } } })
  vm.runInContext(source.slice(entry.start, entry.end), context)
  await context.exportGeoVariant(1, 14, 'website', 'revision')
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [['/api/v1/geo/content-tasks/14/export', { expected_revision: 'revision' }, { params: { tenant_id: 1, channel: 'website' } }]])
})

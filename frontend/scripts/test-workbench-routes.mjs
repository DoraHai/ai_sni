import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = relative => readFileSync(new URL(relative, import.meta.url), 'utf8')
const router = read('../src/router/index.js')
const cockpit = read('../src/views/workspace/AcquisitionCockpitView.vue')
const workspace = read('../src/views/workspace/ModuleWorkspaceView.vue')

assert.match(router, /\['seo\.site',\s*'\/seo\/site'\]/, 'production SEO site route must remain registered')
assert.match(cockpit, /code === 'seo' \? '\/seo\/site'/, 'cockpit SEO action must use the registered route')
assert.match(workspace, /entry: '\/seo\/site'/, 'module workspace SEO entry must use the registered route')
assert.doesNotMatch(`${cockpit}\n${workspace}`, /\/seo\/sites/, 'obsolete SEO route must not remain in workspace entry points')

console.log('Workbench module route contracts passed')

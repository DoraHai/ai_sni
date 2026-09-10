import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import { GEO_DEMO_HOME, isGeoDemoIdentity } from '../src/utils/geoDemoIdentity.js'

const here = dirname(fileURLToPath(import.meta.url))
const router = await readFile(resolve(here, '../geo-frontend/src/router.js'), 'utf8')
const view = await readFile(resolve(here, '../src/views/geo/GeoDemoView.vue'), 'utf8')

const identity = { id: 5, username: 'workbench_test_readonly', tenant_id: 16 }
assert.equal(GEO_DEMO_HOME, '/geo/demo/overview')
assert.equal(isGeoDemoIdentity(identity, 16), true)
assert.equal(isGeoDemoIdentity({ ...identity, id: 6 }, 16), false)
assert.equal(isGeoDemoIdentity({ ...identity, username: 'other' }, 16), false)
assert.equal(isGeoDemoIdentity({ ...identity, tenant_id: 15 }, 16), false)
assert.equal(isGeoDemoIdentity(identity, 15), false)

for (const path of ['demo/overview', 'demo/questions', 'demo/answers', 'demo/tasks']) {
  assert.match(router, new RegExp(`path: '${path.replace('/', '\\/')}'`))
}
assert.match(router, /!to\.path\.startsWith\('\/geo\/demo'\)/)
assert.doesNotMatch(view, /from ['"]\.\.\/\.\.\/api\/geoContent['"]/)
assert.match(view, /from ['"]\.\.\/\.\.\/api\/geoReadModel['"]/)
assert.match(view, /const generation = \+\+loadGeneration/)
assert.match(view, /if \(generation !== loadGeneration\) return/)
assert.match(view, /overview: 'GEO 演示总览'/)

console.log('geo demo identity and route boundary tests passed')

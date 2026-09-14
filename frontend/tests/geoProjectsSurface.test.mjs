import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = (relative) => fs.readFileSync(path.join(root, relative), 'utf8')

test('GEO project management is routed and permission-scoped', () => {
  const router = read('geo-frontend/src/router.js')
  const navigation = read('src/utils/geoPrototypeNavigation.js')
  const shell = read('src/views/geo/GeoWorkspaceShell.vue')

  assert.match(router, /path: 'projects'.*GeoProjectsView\.vue.*perm: 'geo\.assets'/)
  assert.match(navigation, /label: '项目管理'.*path: '\/geo\/projects'.*key: 'geo\.assets'/)
  assert.match(shell, /devBypass \|\| !item\.key \|\| session\.canView\(item\.key\)/)
  assert.match(shell, /v-for="\(group, groupIndex\) in visibleNavigation"/)
})

test('GEO project page reuses the shared project APIs and hides writes from viewers', () => {
  const page = read('src/views/geo/GeoProjectsView.vue')

  const api = read('src/api/geoProjects.js')
  const moduleAssets = read('src/api/moduleAssets.js')

  assert.match(page, /fetchGeoProjects/)
  assert.match(page, /createGeoProject/)
  assert.match(page, /updateGeoProject/)
  assert.match(page, /session\.canEdit\('geo\.assets'\)/)
  assert.match(page, /v-if="canEdit"/)
  assert.match(page, /tenantId\.value !== requestedTenantId/)
  assert.match(api, /client\.get\('\/api\/v1\/geo\/projects'/)
  assert.match(moduleAssets, /export \{ createGeoProject, fetchGeoProjects, updateGeoProject \} from '\.\/geoProjects'/)
})

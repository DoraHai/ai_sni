import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const componentsDir = resolve(import.meta.dirname, '../src/components')

test('GEO prototype layout components expose their public contracts', () => {
  for (const [file, tokens] of Object.entries({
    'GeoPrototypePageHeader.vue': ['defineProps', 'title', 'sub', 'name="actions"'],
    'GeoPrototypeToolbar.vue': ['name="filters"', 'name="actions"'],
    'GeoPrototypeTableSection.vue': ['emptyText', 'name="footer"'],
    'GeoPrototypeContextNotice.vue': ['message', "defineEmits(['retry'])"],
  })) {
    const source = readFileSync(resolve(componentsDir, file), 'utf8')
    tokens.forEach((token) => assert.ok(source.includes(token), `${file} missing ${token}`))
  }
})

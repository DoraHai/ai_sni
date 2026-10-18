import assert from 'node:assert/strict'
import test from 'node:test'
import { safeGeoWebsiteUrl } from '../src/utils/geoWebsiteUrl.js'

test('website links only use complete credential-free HTTP URLs', () => {
  assert.equal(safeGeoWebsiteUrl('https://brand.example.test/about'), 'https://brand.example.test/about')
  for (const value of ['javascript:document.title=String(1)', 'java\nscript:alert(1)',
    'data:text/html,fixture', '//brand.example.test', 'https://user:pass@brand.example.test',
    'http://[', 'https://brand.example.test/space here']) {
    assert.equal(safeGeoWebsiteUrl(value), '', value)
  }
})

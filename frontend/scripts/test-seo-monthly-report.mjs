import test from 'node:test'
import assert from 'node:assert/strict'
import { defaultReportSections, moveReportSection, validReportSections, monthlyReportError } from '../src/api/seoMonthlyReport.js'
import { publicationListFilename } from '../src/api/seoPublicationExport.js'

test('default sections are complete and moving preserves the input', () => {
  assert.equal(validReportSections(defaultReportSections), true)
  const moved = moveReportSection(defaultReportSections, 0, 1)
  assert.deepEqual(moved.slice(0, 2).map(item => item.key), ['traffic', 'cover'])
  assert.equal(defaultReportSections[0].key, 'cover')
  assert.equal(moveReportSection(defaultReportSections, 0, -1)[0].key, 'cover')
})

test('section validation rejects duplicates, blank titles and all hidden', () => {
  const clone = () => defaultReportSections.map(item => ({ ...item }))
  const duplicate = clone(); duplicate[0].key = duplicate[1].key
  assert.equal(validReportSections(duplicate), false)
  const blank = clone(); blank[0].title = ' '
  assert.equal(validReportSections(blank), false)
  const hidden = clone(); hidden.forEach(item => { item.enabled = false })
  assert.equal(validReportSections(hidden), false)
})

test('PDF filename and Chinese blob error are decoded', async () => {
  assert.equal(publicationListFilename("attachment; filename*=UTF-8''SEO%E6%9C%88%E6%8A%A5.pdf", 'fallback.pdf'), 'SEO月报.pdf')
  const error = { response: { data: new Blob([JSON.stringify({ detail: { message: '生成超时，请稍后重试' } })]) } }
  assert.equal(await monthlyReportError(error), '生成超时，请稍后重试')
})

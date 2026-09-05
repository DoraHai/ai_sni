import test from 'node:test'
import assert from 'node:assert/strict'
import { applyAliasMap } from '../src/utils/competitorAlias.js'
const row = (name, ids, prompts, urls) => ({name,snapshot_ids:ids,prompt_ids:prompts,source_urls:urls,mention_count:ids.length,prompt_count:prompts.length,source_count:urls.length,engines:['kimi'],platform_keys:['website']})
test('manual aliases deduplicate overlapping evidence and preserve inputs', () => {
 const rows=[row('ibm',[1,2],[7],['https://a']),row('international business machines',[2,3],[7,8],['https://a','https://b'])]
 const saved=JSON.stringify(rows)
 const result=applyAliasMap(rows,{'IBM':'IBM','International Business Machines':'IBM'})
 assert.equal(result.length,1)
 assert.equal(result[0].mention_count,3)
 assert.equal(result[0].prompt_count,2)
 assert.equal(result[0].source_count,2)
 assert.equal(JSON.stringify(rows),saved)
})
test('legacy rows without evidence cannot invent a deduplicated total', () => {
 const result=applyAliasMap([{name:'A',mention_count:4},{name:'B',mention_count:4}],{A:'X',B:'X'})
 assert.equal(result.length,2)
 assert.deepEqual(result.map(x=>x.name),['A','B'])
})

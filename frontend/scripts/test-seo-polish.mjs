import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { computed, reactive, ref } from 'vue'

function scriptFixture(file, names, extra = {}) {
  const source = readFileSync(new URL(`../src/views/seo/${file}.vue`, import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  const bindings = { computed, reactive, ref, watch(){}, onMounted(){}, onBeforeUnmount(){},
    useRoute:()=>({query:{}}), useRouter:()=>({push(){}}), siteId:ref(1), currentTenantId:ref(1),
    session:{isLoggedIn:true,canEdit:()=>false}, defineProps:()=>({tenantId:1,siteId:1}), ...extra }
  return new Function(...Object.keys(bindings), `${script};return {${names}}`)(...Object.values(bindings))
}

test('image coverage distinguishes no candidates, an unreviewed sample and approved samples',()=>{
  const f=scriptFixture('SeoImageRemediationWorkbench','result,coverage')
  for (const [stats, expected] of [[{},'暂无数据'],[{candidate_count:0,approved_count:0},'暂无数据'],
    [{candidate_count:2,approved_count:0},'0%'],[{candidate_count:2,approved_count:1},'50%']]) {
    f.result.value.stats=stats; assert.equal(f.coverage.value,expected)
  }
})

test('issue centre only claims no problems when an assessed page exists',()=>{
  const f=scriptFixture('SeoSiteOptimizationView','issueResult,issueEmptyText')
  for (const summary of [{},{assessed_pages:0}]) {
    f.issueResult.value.summary=summary; assert.match(f.issueEmptyText.value,/未检测或暂无可评估数据/)
  }
  f.issueResult.value.summary={assessed_pages:1}
  assert.equal(f.issueEmptyText.value,'最近检测没有发现站内问题')
})

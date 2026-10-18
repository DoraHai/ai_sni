import assert from 'node:assert/strict'
class Storage {
  values = new Map()
  get length() { return this.values.size }
  key(i) { return [...this.values.keys()][i] }
  getItem(k) { return this.values.get(k) ?? null }
  setItem(k, v) { this.values.set(k, String(v)) }
  removeItem(k) { this.values.delete(k) }
}
globalThis.window = new EventTarget()
globalThis.localStorage = new Storage()
globalThis.sessionStorage = new Storage()
const { session } = await import('../src/store/session.js')
const jwt = claims => `e30.${Buffer.from(JSON.stringify({ sub: '7', ...claims })).toString('base64url')}.fixture`
const identity = jwt({ scope_kind: 'advisor_identity', aud: 'advisor-session' })
const business = (tid, gid) => jwt({ scope_kind: 'advisor_tenant', aud: 'advisor-business', tid, gid })
const user = { id: 7, tenant_id: 1, is_advisor: true, permissions: { 'seo.site': 'edit', 'seo.content': 'edit' } }
session.setAuth(identity, user, true)
assert.equal(session.tenantId, null)
session.setTenants([{ id: 1 }, { id: 2 }])
assert.equal(session.tenantId, null)
session.setTenant(3)
assert.equal(session.tenantId, null)
sessionStorage.setItem('seo_pending_rewrite_source', 'old-customer-draft')
sessionStorage.setItem('sem_builder_handoff_1', 'old-handoff')
sessionStorage.setItem('seo_site_id', '19')
const oldRevision = session.authRevision
session.replaceAuthForAdvisorTenant(business(2, 20), 2)
assert.equal(session.tenantId, 2)
assert.equal(session.user.tenant_id, 1)
assert.equal(session.advisorGrantId, 20)
assert(session.authRevision > oldRevision)
assert.equal(sessionStorage.getItem('seo_pending_rewrite_source'), null)
assert.equal(sessionStorage.getItem('sem_builder_handoff_1'), null)
assert.equal(sessionStorage.getItem('seo_site_id'), null)
assert.equal(JSON.parse(localStorage.getItem('sem_auth_v1')).token, identity)
assert.equal(JSON.parse(sessionStorage.getItem('sem_auth_v1')).token, session.token)
session.refreshUser(user)
assert.equal(session.tenantId, 2)
session.setTenant(3)
assert.equal(session.tenantId, 2)
assert.throws(() => session.replaceAuthForAdvisorTenant(business(3, 30), 2))
assert(session.restoreAdvisorIdentity())
assert.equal(session.token, identity)
assert.equal(session.tenantId, null)
assert.deepEqual(session.modules, [])
session.replaceAuthForAdvisorTenant(business(1, 11), 1)
session.replaceAuthForAdvisorTenant(business(2, 21), 2)
assert.equal(session.advisorGrantId, 21)
session.logout()
assert.equal(sessionStorage.getItem('sem_advisor_identity_v1'), null)
console.log('advisor session: identity, tab isolation, cleanup and grant recovery passed')

import assert from 'node:assert/strict'
import test from 'node:test'

import { persistentAuthForEvent, readAuthPair, selectStoredAuth } from '../src/store/sessionStorage.js'

function memory(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  }
}

const user = (id, tenantId = null) => JSON.stringify({ id, tenant_id: tenantId, permissions: { 'geo.content': 'view' } })

test('token and user are accepted only as a valid pair from one storage', () => {
  const local = memory({ sem_token: 'local-token' })
  const session = memory({ sem_user: user(2) })
  assert.equal(readAuthPair(local), null)
  assert.equal(readAuthPair(session), null)
  assert.equal(selectStoredAuth(local, session), null)

  local.setItem('sem_user', '{bad json')
  assert.equal(selectStoredAuth(local, session), null)
})

test('an explicit tab session wins over a persistent login from another tab', () => {
  const local = memory({ sem_token: 'local-token', sem_user: user(1, 10) })
  const session = memory({ sem_token: 'tab-token', sem_user: user(2, 20) })
  assert.deepEqual(selectStoredAuth(local, session), {
    token: 'tab-token', user: JSON.parse(user(2, 20)), storage: 'session',
  })
  assert.equal(persistentAuthForEvent({
    event: { key: 'sem_token', storageArea: local }, localStore: local,
    sessionStore: session, currentStorage: 'session',
  }), undefined)
})

test('persistent login refresh and logout are synchronized without carrying tenant state', () => {
  const local = memory({ sem_token: 'new-token', sem_user: user(3, null) })
  const session = memory({ sem_tenant_id: '99' })
  assert.deepEqual(persistentAuthForEvent({
    event: { key: 'sem_token', storageArea: local }, localStore: local,
    sessionStore: session, currentStorage: 'local',
  }), { token: 'new-token', user: JSON.parse(user(3, null)), storage: 'local' })

  local.removeItem('sem_token')
  assert.equal(persistentAuthForEvent({
    event: { key: 'sem_token', storageArea: local }, localStore: local,
    sessionStore: session, currentStorage: 'local',
  }), null)
})

test('unrelated and sessionStorage events do not mutate persistent identity', () => {
  const local = memory({ sem_token: 'token', sem_user: user(1) })
  const session = memory()
  assert.equal(persistentAuthForEvent({
    event: { key: 'theme', storageArea: local }, localStore: local,
    sessionStore: session, currentStorage: 'local',
  }), undefined)
  assert.equal(persistentAuthForEvent({
    event: { key: 'sem_token', storageArea: session }, localStore: local,
    sessionStore: session, currentStorage: 'local',
  }), undefined)
})


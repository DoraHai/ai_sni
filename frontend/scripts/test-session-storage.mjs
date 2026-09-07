import assert from 'node:assert/strict'
import test from 'node:test'

import {
  AUTH_ENVELOPE_KEY,
  persistentAuthForEvent,
  readAuthPair,
  selectStoredAuth,
  writeAuthEnvelope,
} from '../src/store/sessionStorage.js'

function memory(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  }
}

const user = (id, tenantId = null) => ({ id, tenant_id: tenantId, permissions: { 'geo.content': 'view' } })

test('legacy token and user are accepted only as a valid pair from one storage', () => {
  const local = memory({ sem_token: 'local-token' })
  const session = memory({ sem_user: JSON.stringify(user(2)) })
  assert.equal(readAuthPair(local), null)
  assert.equal(readAuthPair(session), null)
  assert.equal(selectStoredAuth(local, session), null)

  local.setItem('sem_user', '{bad json')
  assert.equal(selectStoredAuth(local, session), null)

  local.setItem('sem_user', JSON.stringify(user(1)))
  local.setItem('sem_auth_v1', '{bad envelope')
  assert.equal(selectStoredAuth(local, session), null)
})

test('an explicit tab session wins over a persistent login from another tab', () => {
  const local = memory()
  const session = memory()
  writeAuthEnvelope(local, 'local-token', user(1, 10))
  writeAuthEnvelope(session, 'tab-token', user(2, 20))
  assert.deepEqual(selectStoredAuth(local, session), {
    token: 'tab-token', user: user(2, 20), storage: 'session',
  })
  assert.equal(persistentAuthForEvent({
    event: { key: AUTH_ENVELOPE_KEY, storageArea: local }, localStore: local,
    sessionStore: session, currentStorage: 'session',
  }), undefined)
})

test('legacy key events never publish a mixed persistent identity', () => {
  const local = memory()
  const session = memory()
  writeAuthEnvelope(local, 'old-token', user(1, 10))

  local.setItem('sem_user', JSON.stringify(user(2, 20)))
  assert.equal(persistentAuthForEvent({
    event: { key: 'sem_user', storageArea: local }, localStore: local,
    sessionStore: session, currentStorage: 'local',
  }), undefined)
  local.setItem('sem_token', 'new-token')
  assert.equal(persistentAuthForEvent({
    event: { key: 'sem_token', storageArea: local }, localStore: local,
    sessionStore: session, currentStorage: 'local',
  }), undefined)

  assert.deepEqual(persistentAuthForEvent({
    event: { key: AUTH_ENVELOPE_KEY, storageArea: local }, localStore: local,
    sessionStore: session, currentStorage: 'local',
  }), { token: 'old-token', user: user(1, 10), storage: 'local' })

  writeAuthEnvelope(local, 'new-token', user(2, 20))
  assert.deepEqual(persistentAuthForEvent({
    event: { key: AUTH_ENVELOPE_KEY, storageArea: local }, localStore: local,
    sessionStore: session, currentStorage: 'local',
  }), { token: 'new-token', user: user(2, 20), storage: 'local' })
})

test('persistent envelope removal synchronizes logout', () => {
  const local = memory()
  const session = memory()
  writeAuthEnvelope(local, 'token', user(1))
  local.removeItem(AUTH_ENVELOPE_KEY)
  assert.equal(persistentAuthForEvent({
    event: { key: AUTH_ENVELOPE_KEY, storageArea: local }, localStore: local,
    sessionStore: session, currentStorage: 'local',
  }), null)
})

test('a legacy client logout remains fail closed during migration', () => {
  const local = memory()
  const session = memory()
  writeAuthEnvelope(local, 'legacy-token', user(1))
  local.removeItem('sem_token')
  assert.equal(persistentAuthForEvent({
    event: { key: 'sem_token', newValue: null, storageArea: local }, localStore: local,
    sessionStore: session, currentStorage: 'local',
  }), null)
})

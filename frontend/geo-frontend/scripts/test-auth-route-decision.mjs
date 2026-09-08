import assert from 'node:assert/strict'
import test from 'node:test'

import { geoSessionRouteDecision } from '../src/authRouteDecision.js'

function decide({ loggedIn = true, level = 'view', route = { meta: { perm: 'geo.content' } }, devBypass = false } = {}) {
  const calls = []
  const result = geoSessionRouteDecision({
    route,
    session: {
      isLoggedIn: loggedIn,
      canView: permission => permission === 'geo.content' && ['view', 'edit'].includes(level),
    },
    devBypass,
    redirectToLogin: () => calls.push('login'),
    leaveWorkspace: () => { calls.push('portal'); return false },
  })
  return { result, calls }
}

test('public GEO route remains accessible without a session', () => {
  assert.deepEqual(decide({ loggedIn: false, level: undefined, route: { meta: { public: true } } }), {
    result: true,
    calls: [],
  })
})

test('missing session redirects to login', () => {
  assert.deepEqual(decide({ loggedIn: false }), { result: false, calls: ['login'] })
})

test('ordinary view and edit roles can open GEO routes', () => {
  assert.deepEqual(decide({ level: 'view' }), { result: true, calls: [] })
  assert.deepEqual(decide({ level: 'edit' }), { result: true, calls: [] })
})

test('a logged-in role without geo.content leaves the GEO workspace', () => {
  assert.deepEqual(decide({ level: 'none' }), { result: false, calls: ['portal'] })
})

test('development API-key bypass remains explicit policy input', () => {
  assert.deepEqual(decide({ loggedIn: false, level: undefined, devBypass: true }), {
    result: true,
    calls: [],
  })
})

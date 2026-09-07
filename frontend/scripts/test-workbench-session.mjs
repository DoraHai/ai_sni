import assert from 'node:assert/strict'
import { reactive } from 'vue'

import { useWorkbenchSession } from '../src/composables/useWorkbenchSession.js'

function createSession(overrides = {}) {
  return reactive({
    token: 'token-a',
    user: { id: 5, permissions: { 'monitor.dashboard': 'view' } },
    tenantId: 16,
    demo: false,
    ...overrides,
  })
}

{
  const session = createSession()
  const observed = []
  let readTransportSession = () => null
  const adapter = useWorkbenchSession({
    session,
    invalidatables: [
      () => observed.push(readTransportSession()),
      () => { throw new Error('contains token-a but must never escape') },
      { invalidate: () => observed.push('last') },
    ],
  })
  readTransportSession = adapter.getTransportSession

  assert.equal(adapter.scope.value.userId, 5)
  assert.equal(adapter.scope.value.tenantId, 16)
  assert.deepEqual(adapter.scope.value.permissions, { 'monitor.dashboard': 'view' })
  assert.equal(Object.isFrozen(adapter.scope.value.permissions), true)
  assert.deepEqual(adapter.getTransportSession(), { token: 'token-a', revision: 1 })

  // Unrelated demo state is not part of the identity fingerprint.
  const initialCalls = observed.length
  session.demo = true
  assert.equal(observed.length, initialCalls)

  session.tenantId = 17
  assert.equal(observed.at(-2), null, 'transport session must be cleared before invalidation')
  assert.equal(observed.at(-1), 'last', 'a throwing invalidator must not stop later targets')
  assert.deepEqual(adapter.getTransportSession(), { token: 'token-a', revision: 2 })
  assert.equal(adapter.scope.value.tenantId, 17)

  const afterSwitch = observed.length
  session.tenantId = 17
  assert.equal(observed.length, afterSwitch, 'the same fingerprint must not invalidate twice')

  let unregisteredCalls = 0
  const unregister = adapter.registerInvalidatable(() => { unregisteredCalls += 1 })
  unregister()
  unregister()
  assert.equal(unregisteredCalls, 0, 'unregister only detaches the target')
  session.user.permissions['monitor.dashboard'] = 'edit'
  assert.equal(unregisteredCalls, 0)
  assert.equal(adapter.scope.value.authorizationRevision, 3)
  assert.equal(adapter.scope.value.permissions['monitor.dashboard'], 'edit')

  session.token = ''
  assert.equal(adapter.scope.value, null)
  assert.equal(adapter.getTransportSession(), null)
  session.tenantId = null
  assert.equal(adapter.scope.value, null, 'the adapter must not select a tenant')

  const callsBeforeDispose = observed.length
  adapter.dispose()
  assert.equal(observed.length, callsBeforeDispose + 2)
  adapter.dispose()
  assert.equal(observed.length, callsBeforeDispose + 2, 'dispose must be idempotent')
  session.token = 'token-b'
  session.tenantId = 18
  assert.equal(adapter.scope.value, null)

  let lateCalls = 0
  const unregisterLate = adapter.registerInvalidatable(() => { lateCalls += 1 })
  assert.equal(lateCalls, 1, 'registration after dispose must stay fail closed')
  unregisterLate()
}

{
  const permissions = { 'optimize.keywords': 'view' }
  const session = createSession({ user: { id: 8, permissions } })
  let invalidations = 0
  const adapter = useWorkbenchSession({ session, invalidatables: [() => { invalidations += 1 }] })
  const copied = adapter.scope.value.permissions

  permissions['optimize.keywords'] = 'edit'
  assert.equal(copied['optimize.keywords'], 'view', 'published permissions must be a frozen copy')
  assert.equal(invalidations, 1, 'mutating a non-reactive source object cannot alter published scope')

  session.user.permissions = { 'optimize.keywords': 'edit' }
  assert.equal(invalidations, 2)
  assert.equal(adapter.scope.value.permissions['optimize.keywords'], 'edit')
  adapter.dispose()
}

{
  const session = createSession({ user: { id: 5, permissions: [] }, demo: true })
  const adapter = useWorkbenchSession({ session })
  assert.equal(adapter.scope.value, null, 'demo mode and array permissions must not authorize')
  assert.equal(adapter.getTransportSession(), null)
  let invalidRegistrationCalls = 0
  adapter.registerInvalidatable(() => { invalidRegistrationCalls += 1 })
  assert.equal(invalidRegistrationCalls, 1, 'registration without a readable scope must fail closed')
  adapter.dispose()
}

{
  const session = createSession()
  let changeAgain = false
  const adapter = useWorkbenchSession({
    session,
    invalidatables: [() => {
      if (changeAgain && session.tenantId === 18) session.tenantId = 19
    }],
  })
  changeAgain = true
  session.tenantId = 18
  assert.equal(adapter.scope.value.tenantId, 19, 'a nested identity change must win over a stale transition')
  assert.deepEqual(adapter.getTransportSession(), { token: 'token-a', revision: 3 })
  adapter.dispose()
}

console.log('Workbench session adapter tests passed')

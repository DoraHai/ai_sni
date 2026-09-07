import { getCurrentInstance, onBeforeUnmount, readonly, shallowRef, watch } from 'vue'

function isPositiveId(value) {
  return Number.isSafeInteger(value) && value > 0
}

function snapshotSession(session) {
  const token = session?.token
  const userId = session?.user?.id
  const tenantId = session?.tenantId
  const sourcePermissions = session?.user?.permissions
  const permissionsValid = sourcePermissions !== null
    && typeof sourcePermissions === 'object'
    && !Array.isArray(sourcePermissions)
  const permissionEntries = permissionsValid
    ? Object.keys(sourcePermissions).sort().map((key) => [key, sourcePermissions[key]])
    : []
  const permissionValuesValid = permissionEntries.every(([, value]) => value === 'view' || value === 'edit')

  const ready = typeof token === 'string'
    && token.length > 0
    && !/\s/.test(token)
    && isPositiveId(userId)
    && isPositiveId(tenantId)
    && permissionsValid
    && permissionValuesValid

  return {
    token,
    userId,
    tenantId,
    permissionEntries,
    ready,
    fingerprint: JSON.stringify([
      typeof token === 'string' ? token : null,
      isPositiveId(userId) ? userId : `${typeof userId}:${String(userId)}`,
      isPositiveId(tenantId) ? tenantId : `${typeof tenantId}:${String(tenantId)}`,
      permissionsValid && permissionValuesValid ? permissionEntries : null,
    ]),
  }
}

function callInvalidator(target) {
  try {
    if (typeof target === 'function') target()
    else target.invalidate()
  } catch {
    // One client must not prevent the remaining clients from being invalidated.
  }
}

/**
 * Adapts the in-memory SEM session to the workbench read-only clients.
 * A non-null scope means only that the host identity is complete. Each module
 * client must still run its own server-side authorization preflight.
 */
export function useWorkbenchSession({ session, invalidatables = [] } = {}) {
  if (!session || !Array.isArray(invalidatables)) throw new TypeError('INVALID_SESSION_ADAPTER')

  const scopeState = shallowRef(null)
  const targets = new Set()
  let currentToken = null
  let currentFingerprint
  let authorizationRevision = 0
  let disposed = false

  function invalidateAll() {
    for (const target of [...targets]) callInvalidator(target)
  }

  function registerInvalidatable(target) {
    if (typeof target !== 'function' && typeof target?.invalidate !== 'function') {
      throw new TypeError('INVALID_INVALIDATABLE')
    }
    if (disposed) {
      callInvalidator(target)
      return () => {}
    }
    targets.add(target)
    if (!scopeState.value) callInvalidator(target)
    let registered = true
    // Unregistering only stops future notifications; it does not mutate the client.
    return () => {
      if (!registered) return
      registered = false
      targets.delete(target)
    }
  }

  for (const target of invalidatables) {
    if (typeof target !== 'function' && typeof target?.invalidate !== 'function') {
      throw new TypeError('INVALID_INVALIDATABLE')
    }
    targets.add(target)
  }

  const stop = watch(
    () => snapshotSession(session),
    (candidate) => {
      if (disposed || candidate.fingerprint === currentFingerprint) return
      currentFingerprint = candidate.fingerprint
      authorizationRevision += 1
      const transitionRevision = authorizationRevision

      // Clear the readable session before callbacks can abort requests or clear
      // module authorization state. A callback can therefore never see old auth.
      currentToken = null
      scopeState.value = null
      invalidateAll()

      // An invalidator may synchronously change identity or dispose this adapter.
      if (disposed || transitionRevision !== authorizationRevision || !candidate.ready) return
      const permissions = Object.freeze(Object.fromEntries(candidate.permissionEntries))
      currentToken = candidate.token
      scopeState.value = Object.freeze({
        userId: candidate.userId,
        tenantId: candidate.tenantId,
        permissions,
        authorizationRevision,
      })
    },
    { immediate: true, flush: 'sync' },
  )

  function getTransportSession() {
    if (disposed || !currentToken || !scopeState.value) return null
    return Object.freeze({ token: currentToken, revision: authorizationRevision })
  }

  function dispose() {
    if (disposed) return
    disposed = true
    stop()
    authorizationRevision += 1
    currentToken = null
    scopeState.value = null
    invalidateAll()
    targets.clear()
  }

  if (getCurrentInstance()) onBeforeUnmount(dispose)

  return Object.freeze({
    scope: readonly(scopeState),
    getTransportSession,
    registerInvalidatable,
    dispose,
  })
}

export const TOKEN_KEY = 'sem_token'
export const USER_KEY = 'sem_user'
export const AUTH_ENVELOPE_KEY = 'sem_auth_v1'
export const AUTH_CONTEXT_EVENT = 'sem:auth-context-changed'

function validUser(value) {
  return value !== null
    && typeof value === 'object'
    && !Array.isArray(value)
    && Number.isSafeInteger(value.id)
    && value.id > 0
    && (value.tenant_id === null || (Number.isSafeInteger(value.tenant_id) && value.tenant_id > 0))
    && value.permissions !== null
    && typeof value.permissions === 'object'
    && !Array.isArray(value.permissions)
    && Object.values(value.permissions).every((level) => level === 'view' || level === 'edit')
}

function validToken(token) {
  return typeof token === 'string' && !!token && !/\s/.test(token)
}

export function readAuthEnvelope(storage) {
  const raw = storage?.getItem?.(AUTH_ENVELOPE_KEY)
  if (!raw) return null
  try {
    const value = JSON.parse(raw)
    return value?.version === 1 && validToken(value.token) && validUser(value.user)
      ? { token: value.token, user: value.user }
      : null
  } catch {
    return null
  }
}

export function readLegacyAuthPair(storage) {
  const token = storage?.getItem?.(TOKEN_KEY)
  const rawUser = storage?.getItem?.(USER_KEY)
  if (!validToken(token) || !rawUser) return null
  try {
    const user = JSON.parse(rawUser)
    return validUser(user) ? { token, user } : null
  } catch {
    return null
  }
}

export function readAuthPair(storage) {
  if (storage?.getItem?.(AUTH_ENVELOPE_KEY) !== null) return readAuthEnvelope(storage)
  return readLegacyAuthPair(storage)
}

export function writeAuthEnvelope(storage, token, user) {
  if (!validToken(token) || !validUser(user)) throw new TypeError('INVALID_AUTH_ENVELOPE')
  storage.setItem(USER_KEY, JSON.stringify(user))
  storage.setItem(TOKEN_KEY, token)
  storage.setItem(AUTH_ENVELOPE_KEY, JSON.stringify({ version: 1, token, user }))
}

export function clearStoredAuth(storage) {
  storage.removeItem(AUTH_ENVELOPE_KEY)
  storage.removeItem(TOKEN_KEY)
  storage.removeItem(USER_KEY)
}

export function selectStoredAuth(localStore, sessionStore) {
  const transient = readAuthPair(sessionStore)
  if (transient) return { ...transient, storage: 'session' }
  const persistent = readAuthPair(localStore)
  return persistent ? { ...persistent, storage: 'local' } : null
}

export function persistentAuthForEvent({ event, localStore, sessionStore, currentStorage }) {
  if (event?.storageArea !== localStore) {
    return undefined
  }
  if (currentStorage === 'session' && readAuthPair(sessionStore)) return undefined
  if ((event.key === TOKEN_KEY || event.key === USER_KEY)
      && event.newValue === null) return null
  if (event.key !== AUTH_ENVELOPE_KEY && event.key !== null) return undefined
  const persistent = readAuthEnvelope(localStore)
  return persistent ? { ...persistent, storage: 'local' } : null
}

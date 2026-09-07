const TOKEN_KEY = 'sem_token'
const USER_KEY = 'sem_user'

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

export function readAuthPair(storage) {
  const token = storage?.getItem?.(TOKEN_KEY)
  const rawUser = storage?.getItem?.(USER_KEY)
  if (typeof token !== 'string' || !token || /\s/.test(token) || !rawUser) return null
  try {
    const user = JSON.parse(rawUser)
    return validUser(user) ? { token, user } : null
  } catch {
    return null
  }
}

export function selectStoredAuth(localStore, sessionStore) {
  // A tab-local login is an explicit identity choice and must not be replaced
  // when another tab creates or refreshes a persistent login.
  const transient = readAuthPair(sessionStore)
  if (transient) return { ...transient, storage: 'session' }
  const persistent = readAuthPair(localStore)
  return persistent ? { ...persistent, storage: 'local' } : null
}

export function persistentAuthForEvent({ event, localStore, sessionStore, currentStorage }) {
  if (event?.storageArea !== localStore || (event.key !== TOKEN_KEY && event.key !== USER_KEY && event.key !== null)) {
    return undefined
  }
  if (currentStorage === 'session' && readAuthPair(sessionStore)) return undefined
  const persistent = readAuthPair(localStore)
  return persistent ? { ...persistent, storage: 'local' } : null
}

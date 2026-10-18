// Same envelope and tab precedence as the production SEM frontend.
const AUTH_ENVELOPE_KEY = 'sem_auth_v1'

function validUser(user) {
  return user !== null && typeof user === 'object' && !Array.isArray(user)
    && Number.isSafeInteger(user.id) && user.id > 0
    && (user.tenant_id === null || (Number.isSafeInteger(user.tenant_id) && user.tenant_id > 0))
    && user.permissions !== null && typeof user.permissions === 'object' && !Array.isArray(user.permissions)
    && Object.values(user.permissions).every((level) => level === 'view' || level === 'edit')
}

const validToken = (token) => typeof token === 'string' && !!token && !/\s/.test(token)

function readAuthPair(storage) {
  try {
    const raw = storage.getItem(AUTH_ENVELOPE_KEY)
    const pair = raw !== null ? JSON.parse(raw) : {
      token: storage.getItem('sem_token'), user: JSON.parse(storage.getItem('sem_user') || 'null'),
    }
    if (raw !== null && pair?.version !== 1) return null
    return validToken(pair?.token) && validUser(pair?.user) ? pair : null
  } catch { return null }
}

export function selectStoredAuth(localStore, sessionStore) {
  const transient = readAuthPair(sessionStore)
  if (transient) return { token: transient.token, user: transient.user, storage: 'session' }
  const persistent = readAuthPair(localStore)
  return persistent ? { token: persistent.token, user: persistent.user, storage: 'local' } : null
}

export function writeAuthEnvelope(storage, token, user) {
  if (!validToken(token) || !validUser(user)) throw new TypeError('INVALID_AUTH_ENVELOPE')
  storage.setItem('sem_user', JSON.stringify(user))
  storage.setItem('sem_token', token)
  storage.setItem(AUTH_ENVELOPE_KEY, JSON.stringify({ version: 1, token, user }))
}

export function clearStoredAuth(storage) {
  for (const key of [AUTH_ENVELOPE_KEY, 'sem_token', 'sem_user']) storage.removeItem(key)
}

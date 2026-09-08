import { CUSTOMER_ROLE } from '../constants/roles.js'

export function canSubmitGeoReview(user) {
  return user?.permissions?.['geo.content'] === 'edit'
}

export function canDecideGeoReview(user) {
  const level = user?.permissions?.['geo.content']
  return level === 'edit' || (
    level === 'view'
    && user?.id != null
    && user?.tenant_id != null
    && user?.role_label === CUSTOMER_ROLE
  )
}

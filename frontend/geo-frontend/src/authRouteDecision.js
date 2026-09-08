export function geoSessionRouteDecision({
  route,
  session,
  devBypass = false,
  redirectToLogin,
  leaveWorkspace,
}) {
  if (route?.meta?.public) return true
  if (!session.isLoggedIn && !devBypass) {
    redirectToLogin()
    return false
  }
  if (devBypass || !route?.meta?.perm || session.canView(route.meta.perm)) return true
  return leaveWorkspace()
}

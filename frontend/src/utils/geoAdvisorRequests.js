// Both visibility pages share the same advisor request contract.
export function advisorVisibilityBody(body, isAdvisor) {
  return isAdvisor ? { tenant_id: body.tenant_id } : body
}

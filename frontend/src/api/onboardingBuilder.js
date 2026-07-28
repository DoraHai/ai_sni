import client from './client'

export function generateBuildDraft(payload) {
  return client.post('/api/v1/onboarding-builder/draft', {
    tenant_id: payload.tenantId,
    landing_url: payload.landingUrl || null,
    landing_text: payload.landingText || null,
    business_summary: payload.businessSummary,
    goal: payload.goal,
    budget: payload.budget || null,
    regions: payload.regions || null,
    schedule: payload.schedule || null,
    schedule_blocks: payload.scheduleBlocks || null,
    device_preference: payload.devicePreference || '不限',
  }, { timeout: 120000 })
}

export function applyBuildDraft(payload) {
  return client.post('/api/v1/onboarding-builder/apply', {
    tenant_id: payload.tenantId,
    draft: payload.draft,
  }, { timeout: 120000 })
}

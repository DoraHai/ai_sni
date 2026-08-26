import client from './client'

// 投放管理 · 账户与预算（menu = manage.account）。
export function fetchAccountBudget({ tenantId, baiduAccountId = null }) {
  return client.get('/api/v1/manage/account-budget', {
    params: { tenant_id: tenantId, baidu_account_id: baiduAccountId },
  })
}

// 写回账户日预算（dry-run 演练时只记台账不真改）。
export function setAccountBudget({ tenantId, baiduAccountId = null, budget, approvalId = null }) {
  return client.post('/api/v1/manage/account-budget', {
    tenant_id: tenantId, baidu_account_id: baiduAccountId, budget, approval_id: approvalId,
  })
}

// 计划列表（含日预算/状态，行内可改预算）。
export function fetchCampaigns({ tenantId, baiduAccountId }) {
  return client.get('/api/v1/manage/campaigns', {
    params: { tenant_id: tenantId, baidu_account_id: baiduAccountId || undefined },
  })
}

// 写回计划日预算（dry-run 演练时只记台账不真改）。
export function setCampaignBudget({ tenantId, campaignId, budget, approvalId = null }) {
  return client.post('/api/v1/manage/campaign-budget', {
    tenant_id: tenantId, campaign_id: campaignId, budget, approval_id: approvalId,
  })
}

// 计划启停（pause=true 暂停 / false 恢复投放）。
export function setCampaignPause({ tenantId, campaignId, pause }) {
  return client.post('/api/v1/manage/campaign-pause', {
    tenant_id: tenantId, campaign_id: campaignId, pause,
  })
}

// 整表写回计划投放时段；pause=true 用于节假日停投模板。
export function setCampaignSchedule({ tenantId, campaignId, schedulePriceFactors, pause = false }) {
  return client.post('/api/v1/manage/campaign-schedule', {
    tenant_id: tenantId,
    campaign_id: campaignId,
    schedule_price_factors: schedulePriceFactors.map((item) => ({
      time_id: item.timeId,
      price_factor: item.priceFactor,
    })),
    pause,
  })
}

export function fetchRegionOptions() {
  return client.get('/api/v1/manage/region-options')
}

export function setCampaignRegion({ tenantId, campaignId, regionTarget, regionPriceFactor, geoLocationStatus }) {
  return client.post('/api/v1/manage/campaign-region', {
    tenant_id: tenantId,
    campaign_id: campaignId,
    region_target: regionTarget,
    region_price_factor: regionPriceFactor,
    geo_location_status: geoLocationStatus,
  })
}

// 单元列表（出价/启停，行内可改）。
export function fetchAdgroups({ tenantId, campaignId }) {
  return client.get('/api/v1/manage/adgroups', {
    params: { tenant_id: tenantId, campaign_id: campaignId || undefined },
  })
}

// 单元启停。
export function setAdgroupPause({ tenantId, adgroupId, pause }) {
  return client.post('/api/v1/manage/adgroup-pause', {
    tenant_id: tenantId, adgroup_id: adgroupId, pause,
  })
}

// 单元出价写回。
export function setAdgroupBid({ tenantId, adgroupId, maxPrice, approvalId = null }) {
  return client.post('/api/v1/manage/adgroup-bid', {
    tenant_id: tenantId, adgroup_id: adgroupId, max_price: maxPrice, approval_id: approvalId,
  })
}

// 单元落地页 / URL 拆分字段写回。
export function setAdgroupLandingUrl({
  tenantId,
  adgroupId,
  pcFinalUrl,
  mobileFinalUrl,
  pcTrackParam,
  mobileTrackParam,
  pcTrackTemplate,
  mobileTrackTemplate,
}) {
  return client.post('/api/v1/manage/adgroup-landing-url', {
    tenant_id: tenantId,
    adgroup_id: adgroupId,
    pc_final_url: pcFinalUrl,
    mobile_final_url: mobileFinalUrl,
    pc_track_param: pcTrackParam,
    mobile_track_param: mobileTrackParam,
    pc_track_template: pcTrackTemplate,
    mobile_track_template: mobileTrackTemplate,
  })
}

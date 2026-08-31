/**
 * GEO 侧栏 — 对齐 geo-v2 `assets/geo-sidebar-v1.js`
 */
import { GEO_PROTOTYPE_GROUPS, GEO_PROTOTYPE_PAGES, GEO_WORKBENCH_START } from './geoPrototypeContract'

export { GEO_WORKBENCH_START }

export const GEO_WORKBENCH_NAV = GEO_PROTOTYPE_GROUPS.map((group) => ({
  label: group.label,
  children: group.pages.map((id) => {
    const page = GEO_PROTOTYPE_PAGES.find((item) => item.id === id)
    return { label: page.label, path: page.path, key: 'geo.content', icon: page.icon }
  }),
}))

import { reactive } from 'vue'

// Memory only; changing identity/customer invalidates this selection.
export const geoAdvisorProject = reactive({ token: null, tenantId: null, projectId: null })

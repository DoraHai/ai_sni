import { createApp, h } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import Monitor from '../../src/components/GeoPublicationMonitor.vue'
import client from '../../src/api/client'
let state = { publication_id: 4, channel: 'website', url: 'https://example.invalid/article', state: 'mismatch', failures: 2, checked_at: '2026-09-06T05:00:00Z' }
client.defaults.adapter = async config => {
 if (config.method === 'post') state = { ...state, state: 'healthy', failures: 0, checked_at: new Date().toISOString() }
 return { data: config.method === 'get' ? { items: [state] } : state, status: 200, statusText: 'OK', headers: {}, config }
}
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { render: () => null } }] })
createApp({ render: () => h('main', { style: 'max-width:900px;margin:30px auto;font-family:sans-serif' }, [h('h2', '仅内存测试，不请求客户网站'), h(Monitor, { tenantId: 7, taskId: 12 })]) }).use(router).mount('#app')

import axios from 'axios'
import { session } from '../store/session'

// 同源 /api 路径：开发期由 vite proxy 转发，生产由 Nginx 反代
const client = axios.create({
  baseURL: '',
  timeout: 30000,
})

client.interceptors.request.use((config) => {
  if (session.token) {
    config.headers.Authorization = `Bearer ${session.token}`
  } else if (import.meta.env.VITE_API_KEY) {
    // 本地开发兜底:没登录时用 dev API Key(生产 Nginx 不再注入,必须登录)
    config.headers['X-API-Key'] = import.meta.env.VITE_API_KEY
  }
  return config
})

// FastAPI 的 detail 可能是字符串(HTTPException)、数组(422 校验错误
// [{loc,msg,type}])或对象;直接塞进 new Error() 会变成 "[object Object]"
function normalizeDetail(detail) {
  if (detail == null || detail === '') return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
  }
  if (typeof detail === 'object') {
    if (typeof detail.msg === 'string') return detail.msg
    if (typeof detail.message === 'string') return detail.message
    if (typeof detail.detail === 'string') return detail.detail
    try {
      return JSON.stringify(detail)
    } catch {
      return String(detail)
    }
  }
  return String(detail)
}

client.interceptors.response.use(
  (resp) => resp.data,
  async (error) => {
    if (error.response?.status === 401) {
      const devKey =
        import.meta.env.DEV &&
        import.meta.env.VITE_API_KEY &&
        String(import.meta.env.VITE_API_KEY).trim() &&
        import.meta.env.VITE_API_KEY !== 'CHANGE_ME'
          ? String(import.meta.env.VITE_API_KEY).trim()
          : ''
      // Stale JWT: clear + retry once with API Key (avoid silent hang / no toast)
      if (devKey && error.config && !error.config.__geoRetried401) {
        try {
          if (session.isLoggedIn || session.token) session.logout()
        } catch {
          /* ignore */
        }
        const cfg = { ...error.config, __geoRetried401: true }
        cfg.headers = { ...(cfg.headers || {}) }
        delete cfg.headers.Authorization
        cfg.headers['X-API-Key'] = devKey
        return client.request(cfg)
      }
      if (session.isLoggedIn && !devKey) {
        session.logout()
        window.location.href = '/login'
        // Still reject so callers get a toast if navigation is slow
        return Promise.reject(new Error('登录已失效，请重新登录'))
      }
      const detail =
        normalizeDetail(error.response?.data?.detail) ||
        '未授权：请登录或配置 VITE_API_KEY'
      return Promise.reject(new Error(detail))
    }
    const status = error.response?.status
    const detail =
      normalizeDetail(error.response?.data?.detail) ||
      (status === 503
        ? '数据库连不上。请先打开 Docker Desktop 并启动 Postgres，然后刷新。'
        : status === 500
          ? '服务出错，请稍后重试'
          : error.message ||
            '网络异常，请稍后重试')
    return Promise.reject(new Error(detail))
  },
)

export default client

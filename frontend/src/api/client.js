import axios from 'axios'
import { session } from '../store/session'
import { redirectToLogin } from '../auth/loginRedirect'

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
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
  }
  if (typeof detail === 'object') return detail.msg || JSON.stringify(detail)
  return String(detail)
}

client.interceptors.response.use(
  (resp) => resp.data,
  (error) => {
    if (error.response?.status === 401 && session.isLoggedIn) {
      session.logout()
      redirectToLogin()
      return new Promise(() => {}) // 跳转中,挂起后续处理
    }
    const detail =
      normalizeDetail(error.response?.data?.detail) ||
      error.message ||
      '网络异常，请稍后重试'
    return Promise.reject(new Error(detail))
  },
)

export default client

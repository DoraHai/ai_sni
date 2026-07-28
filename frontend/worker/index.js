export default {
  async fetch(request, env) {
    const response = await env.ASSETS.fetch(request)
    if (response.status !== 404 || request.method !== 'GET') return response

    const url = new URL(request.url)
    if (url.pathname.includes('.')) return response

    url.pathname = '/index.html'
    return env.ASSETS.fetch(new Request(url, request))
  },
}

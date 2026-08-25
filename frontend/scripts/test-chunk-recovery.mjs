globalThis.window = {
  location: {
    pathname: '/delivery/report',
    search: '',
    reloadCalls: 0,
    reload() { this.reloadCalls += 1 },
  },
  sessionStorage: {
    data: new Map(),
    getItem(key) { return this.data.get(key) ?? null },
    setItem(key, value) { this.data.set(key, value) },
    removeItem(key) { this.data.delete(key) },
  },
}

const {
  clearChunkRecoveryMarker,
  recoverFromChunkLoadError,
} = await import('../src/router/chunkRecovery.js')

const staleChunk = new Error(
  'Failed to fetch dynamically imported module: /assets/CustomerModulesView-old.js',
)

if (!recoverFromChunkLoadError(staleChunk) || window.location.reloadCalls !== 1) {
  throw new Error('首次旧资源错误没有触发恢复刷新')
}
if (recoverFromChunkLoadError(staleChunk) || window.location.reloadCalls !== 1) {
  throw new Error('同一路径重复错误触发了刷新循环')
}
clearChunkRecoveryMarker()
if (!recoverFromChunkLoadError(staleChunk) || window.location.reloadCalls !== 2) {
  throw new Error('成功导航后没有恢复下一次自愈能力')
}
if (recoverFromChunkLoadError(new Error('普通业务错误'))) {
  throw new Error('普通业务错误不应触发页面刷新')
}

console.log('SEM stale chunk recovery test passed')

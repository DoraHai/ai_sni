# SEM 工作台只读接口发布后交接（2026-09-08）

## 已确认的部署证据

核对时间：2026-09-08 11:16 Asia/Shanghai。

- `GET https://gsnipers.snipers.com.cn/health` 返回 HTTP 200，`service=sem-backend`、`env=prod`、
  `db=ok`、`release_commit=2aa1ff3556f5d3e3d0c2b1c5bebb75fcfdd3ef04`。
- `origin/codex/production-sem-backend` 同样指向 `2aa1ff3556f5d3e3d0c2b1c5bebb75fcfdd3ef04`。
- 该提交是 `Merge PR #466: sync SEM cockpit active account scope`，功能提交为
  `246794abd9271ca16e31c172d09ca5b7121a98ae`。
- 未登录访问 dashboard、keywords、search-terms 三个 cockpit GET 均返回 HTTP 401，未泄露业务数据。
- 生产 workflow 仍要求手动输入当前 `codex/production-sem-backend` 的完整 40 位 SHA；校验、上传、
  应用三个阶段都拒绝过期 SHA。归档 MANIFEST 明确写入 `migration=not-run`，发布选择集包含
  `tests/test_sem_cockpit_details.py` 与 `tests/test_sem_cockpit_readonly.py`。

`/health/sem` 不是 SEM 后端健康检查入口，当前返回门户 404 页面；验收应使用 `/health`。

## 最小真人验收

前置条件：使用已授权的真实登录身份，在 `https://gsnipers.snipers.com.cn` 单一标签页完成。客户选择
“SZ-老虎新材料”（`tenant_id=4`）。测试只读取已有数据，禁止点击同步、刷新数据、投放、调价、否词、
加词、提交执行或任何确认写回按钮。

1. 打开获客工作台，选择“SZ-老虎新材料”，确认 SEM 模块可进入。
2. 查看 SEM 总览日期 `2026-09-01` 至 `2026-09-07`。缺报应显示为空或“无数据”，不能显示为真实零值。
3. 查看关键词列表。默认账户范围只能配置为 active 账户 `12`；归档账户 `4` 必须出现在排除说明中，
   不能混入默认指标。未归属数据如果存在，只能作为单独的 `null/未归属` 桶显示。
4. 点击一条关键词进入详情，核对关键词 ID 与列表一致，并能查看报告、设备、地域、星期×小时及电话按钮
   点击证据状态。`unavailable/partial/no_data` 不能变成 0，电话按钮点击不能写成有效咨询。
5. 查看搜索词列表及同步窗口。只核对已有快照，不点击同步、加词或否词。多窗口必须分别显示，不能汇成
   一个同周期总量。
6. 切回工作台总览，再次确认客户仍为 `tenant_id=4`，没有出现其它客户或其它已知百度账户 ID。
7. 记录浏览器、时间、登录角色、四个 GET 的状态码、关键词 ID、是否通过及截图。不要记录密码、JWT、
   Authorization 请求头或完整客户明细。

若前端尚未接入某个下钻页面，应把结果记为“前端未接入”，同时用下面的 GET-only 核验确认后端；不能把
前端入口缺失写成后端接口失败。

## 登录后 GET-only 核验脚本

在已经登录的同域页面打开浏览器开发者工具 Console，粘贴执行。脚本只读取浏览器现有登录态，不打印、
保存或回传令牌；所有业务请求固定为 GET，未包含同步、投放或写回路径。

```javascript
(async () => {
  'use strict'
  const EXPECTED_ORIGIN = 'https://gsnipers.snipers.com.cn'
  const TENANT_ID = 4
  const ACTIVE_ACCOUNT_ID = 12
  const ARCHIVED_ACCOUNT_ID = 4
  const START = '2026-09-01'
  const END = '2026-09-07'

  if (location.origin !== EXPECTED_ORIGIN) throw new Error('请在正式站点同域页面执行')
  const sessionToken = localStorage.getItem('sem_token') || sessionStorage.getItem('sem_token')
  if (!sessionToken) throw new Error('当前标签页没有登录态，请先人工登录')

  const allowed = [
    /^\/api\/v1\/auth\/me$/,
    /^\/api\/v1\/dashboard\/cockpit\?/,
    /^\/api\/v1\/keywords\/cockpit\?/,
    /^\/api\/v1\/keywords\/cockpit\/\d+\?/,
    /^\/api\/v1\/search-terms\/cockpit\?/,
  ]
  async function get(path) {
    if (!allowed.some(pattern => pattern.test(path))) throw new Error(`拒绝非白名单路径：${path}`)
    if (/[?&](?:key|token|api_key)=/i.test(path)) throw new Error('URL 禁止携带凭据')
    const response = await fetch(path, {
      method: 'GET',
      headers: { Authorization: `Bearer ${sessionToken}` },
      cache: 'no-store',
      credentials: 'omit',
      redirect: 'error',
    })
    if (!response.ok) throw new Error(`${path.split('?')[0]} 返回 HTTP ${response.status}`)
    return response.json()
  }
  function assert(condition, message) {
    if (!condition) throw new Error(message)
  }
  function assertDefaultScope(name, payload) {
    const scope = payload.account_scope || {}
    assert(scope.mode === 'all' && scope.baidu_account_id === null, `${name} 不是默认账户范围`)
    assert(JSON.stringify(scope.configured_account_ids) === JSON.stringify([ACTIVE_ACCOUNT_ID]),
      `${name} 默认账户不是仅账户12`)
    assert(Array.isArray(scope.excluded_archived_account_ids) &&
      scope.excluded_archived_account_ids.includes(ARCHIVED_ACCOUNT_ID), `${name} 未明确排除归档账户4`)
    const knownIds = new Set([
      ...(payload.accounts || []).map(row => row.baidu_account_id),
      ...(payload.items || []).map(row => row.baidu_account_id),
      ...(payload.windows || []).map(row => row.baidu_account_id),
      ...(scope.observed_account_ids || []),
    ].filter(id => id !== null && id !== undefined))
    assert([...knownIds].every(id => id === ACTIVE_ACCOUNT_ID), `${name} 混入其它已知账户：${[...knownIds]}`)
  }

  const identity = await get('/api/v1/auth/me')
  const report = await get(`/api/v1/dashboard/cockpit?tenant_id=${TENANT_ID}&start_date=${START}&end_date=${END}`)
  const keywords = await get(`/api/v1/keywords/cockpit?tenant_id=${TENANT_ID}&page=1&page_size=20`)
  const searchTerms = await get(`/api/v1/search-terms/cockpit?tenant_id=${TENANT_ID}&page=1&page_size=20`)
  assertDefaultScope('dashboard', report)
  assertDefaultScope('keywords', keywords)
  assertDefaultScope('search-terms', searchTerms)
  assert(keywords.total > 0 && keywords.items.length > 0, '老虎关键词列表没有可下钻记录')

  const keywordId = keywords.items[0].keyword_id
  const detail = await get(`/api/v1/keywords/cockpit/${keywordId}?tenant_id=${TENANT_ID}&start_date=${START}&end_date=${END}`)
  assertDefaultScope('keyword-detail', detail)
  assert(detail.keyword_id === keywordId, '详情关键词与列表不一致')

  console.table({
    identity: { ok: true, user_id: identity.id ?? identity.user_id ?? null, role: identity.role_name ?? identity.role ?? null },
    dashboard: { ok: true, accounts: report.account_scope.configured_account_ids.join(','), cost: report.metrics.cost,
      click: report.metrics.click, impression: report.metrics.impression },
    keywords: { ok: true, total: keywords.total, inspected_keyword_id: keywordId },
    keyword_detail: { ok: true, keyword_id: detail.keyword_id,
      phone_status: detail.phone_button_clicks?.status ?? 'not-returned' },
    search_terms: { ok: true, total: searchTerms.total, windows: searchTerms.windows.length,
      mixed_windows: searchTerms.mixed_windows },
  })
  console.info('SEM GET-only 验收完成：未执行同步、投放或写回。')
})().catch(error => console.error('SEM GET-only 验收失败：', error.message))
```

## 回滚基线

- 当前线上与生产分支：`2aa1ff3556f5d3e3d0c2b1c5bebb75fcfdd3ef04`。
- Git 一阶段回滚候选：该 merge 的第一父提交
  `88649dd20b0fe939c153e029ec007d6bb27f0cf9`，也是本次同步前已核对的生产后端版本。
- 公开接口无法确认服务器 `/opt/sem-backend/previous` 当前是否仍指向该提交。实际回滚前，服务器负责人必须
  通过受限部署入口核对 `previous` 的 MANIFEST、完整 SHA、健康检查及数据库兼容性；不能只凭 Git 父提交切换。
- 本次变更无迁移，回滚不需要数据库 downgrade。不得手工修改 release 目录或直接覆盖线上文件。

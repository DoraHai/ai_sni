# Tiger SEO 站点创建交接

本文只定义 `tenant_id=4` 的创建前只读核验和创建后的最小验收。当前阶段不得创建站点、不得使用诺德 `site_id=1`，也不得点击采集、扫描或自动化触发按钮。

## 已核对的实现边界

- 管理界面入口是 `/seo/sites`，菜单权限为 `seo.assets`。页面加载调用 `GET /api/v1/seo/sites?tenant_id=4`；“添加网站”只收集网站名称和域名，保存调用 `POST /api/v1/seo/sites`。
- 列表接口要求 `seo.assets:view`；创建接口要求 `seo.assets:edit`。两者都会校验登录身份的租户范围，并要求客户已开通可用的 SEO 模块。模块状态须为 `active` 或未过期的 `trial`。
- 创建接口只执行域名规范化、插入 `seo_sites`、提交并回读。该处理函数没有 `BackgroundTasks`、队列调用、爬虫调用或采集调用。
- 创建状态固定为 `active`。创建请求不接受 `status`、`site_id`、采集范围或供应商配置。
- 数据库唯一约束是 `(tenant_id, canonical_domain)`。规范化会把主机名转为小写、去掉末尾的点并去掉 `www.`；路径不参与唯一键。重复写入返回 HTTP `409` 和“该客户已经维护了这个 SEO 网站”。

## 创建前只读核验

按顺序执行；任何一步不符合即停止，不发送 POST。

1. 调用 `GET /api/v1/admin/customers`，在 `customers` 中精确找到 `id=4`，由业务负责人确认其名称确为 Tiger。检查其 `modules` 中存在 `module_code="seo"`，且 `available=true`。该接口需要平台超级管理员及 `settings.customers:edit`，普通工作台只读身份不能调用。
2. 调用 `GET /api/v1/seo/sites?tenant_id=4`，保存完整响应作为创建前快照。确认响应只含 Tiger 租户的站点。
3. 在 `sites` 中按 `canonical_domain` 精确查找 `tiger-coatings.cn`。如果存在，无论名称、原始域名或状态为何，都判定为已建站并停止创建；不要通过改变大小写、添加 `www.`、路径或尾点绕过。
4. 可调用 `GET /api/v1/seo/workbench/sites?tenant_id=4` 验证工作台选择器权限。该只读接口需要 `seo.content:view` 或 `seo.site:view`，返回 `selection_policy`；只有 `active` 可选择，`paused` 和 `archived` 只能展示为不可选。它不启动后台任务。
5. UI 核验时，先在全局客户选择器确认 Tiger，再进入 `/seo/sites`。列表应与第 2 步响应一致。只打开“添加网站”弹窗检查字段，不点击“保存”。

创建前列表的最小预期形状：

```json
{
  "sites": [
    {
      "id": 123,
      "tenant_id": 4,
      "name": "已有网站",
      "domain": "https://example.cn/",
      "canonical_domain": "example.cn",
      "default_url": "https://example.cn/",
      "status": "active",
      "created_at": "2026-09-07T12:00:00+08:00"
    }
  ]
}
```

空列表必须表现为 `{"sites":[]}`，不能据此跳过客户归属和模块核验。

## 待真人批准后的最小创建请求

建议只使用站点根地址，避免把路径保存在 `default_url`：

```http
POST /api/v1/seo/sites
Content-Type: application/json
```

```json
{
  "tenant_id": 4,
  "name": "TIGER 老虎中国官网",
  "domain": "https://www.tiger-coatings.cn/"
}
```

字段约束：

| 字段 | 约束 | 预期写入 |
| --- | --- | --- |
| `tenant_id` | 整数，固定为 `4` | `tenant_id=4` |
| `name` | 去首尾空白后非空，最长 120 字符 | `TIGER 老虎中国官网` |
| `domain` | 3–255 字符，必须能解析出含点号的主机名 | 保留去首尾空白后的输入 |
| 服务端生成 | 请求中不得提供 | `canonical_domain=tiger-coatings.cn`、`default_url=https://www.tiger-coatings.cn/`、`status=active` |

成功响应必须包含新 `id`，并同时满足 `tenant_id=4`、上述名称、域名、规范域名、默认地址和状态。HTTP `409` 视为重复，不重试 POST，返回列表重新核对现有记录。

## 创建后“不触发采集”的验证点

创建得到新 `site_id` 后立即执行以下只读检查，时间边界使用成功响应的 `created_at`：

1. 再次调用 `GET /api/v1/seo/sites?tenant_id=4`，确认恰好增加一条记录，并且 `canonical_domain=tiger-coatings.cn` 只出现一次。
2. 调用 `GET /api/v1/seo/site/crawl-runs?tenant_id=4&site_id={new_site_id}&limit=10`。未人工点击“扫描网站”时应返回 `{"runs":[],"snapshots":[]}`。
3. 调用 `GET /api/v1/seo/automation-runs?tenant_id=4&site_id={new_site_id}&limit=100`。该接口会混入 `site_id=null` 的租户级定时汇总，不能要求整个 `items` 为空；应确认不存在 `site_id={new_site_id}` 且 `started_at >= created_at` 的运行记录。
4. 不进入仪表盘点击“更新网站数据”或“扫描网站”，也不调用 `POST /api/v1/seo/site/crawl-runs`、`POST /api/v1/seo/overview/automation-runs/trigger`。
5. 后台每小时可能为所有 `active` 站点写入基于现有库内数据计算的零值指标快照。这不访问目标网站，但意味着不能用“创建后数据库绝对没有任何新增行”作为无采集证据。真正的外部抓取证据以 `seo_crawl_runs`/页面快照为准；排名、竞品、外链和问答任务还分别要求已有关键词、竞品、发布链接或批次，单独创建空站点不会生成这些业务输入。

## 只读失败判定

- `401`：登录态不可用。
- `403 当前账号没有 SEO 网站管理权限`：缺少 `seo.assets` 对应权限。
- `403 当前客户尚未开通 SEO 模块`：`tenant_id=4` 没有 SEO 模块记录。
- `403 当前客户的 SEO 模块未启用或已过期`：模块状态或有效期不满足要求。
- `403 无权访问该客户的数据`：登录身份绑定了其他租户。
- `409 该客户已经维护了这个 SEO 网站`：规范域名重复；停止创建并重新读取列表。

## 当前生产只读观察状态

2026-09-07 尝试通过受控浏览器读取生产 `/seo/sites`。浏览器暴露的现有标签仍位于登录页，后续只读标签绑定连续超时，因此没有取得可归因于超级管理员登录态的生产响应。没有点击、填写或提交任何生产表单。上面的接口、字段和副作用判断来自当前生产基线代码及已通过的隔离 PostgreSQL 契约测试；真人执行前仍需完成第 1–5 项生产只读核验。

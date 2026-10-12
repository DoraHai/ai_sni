# 单账号、单篇 SEO 稿件发布验收入口

本增量只改变独立 Linux 验收入口。基线为 `854eedd1398feb7b4dd6bacc9213309fedd7cc2d`，不修改中央业务、共享鉴权、原生 SEO/GEO 或 SEM，不执行 DDL、不创建真实任务、不请求平台、不部署。原生 SEO 使用 `b4d8387123355348f79e26ea2838585c5106a4b9`。

默认仍拒绝发布。只有固定私有文件 `/opt/gsnipers-distribution-acceptance/work/distribution-server-pilot-20261012/single-publication-seo.json` 有效时，允许这一份精确请求到达原生路由。文件不是设备凭据或原生审核证明；账号核验授权不能升级为发布授权。

## 配置及有效范围

配置样例为 `docs/fixtures/distribution-single-publication-seo.example.json`。样例含无效占位符，直接复制不能打开门禁，不含密钥或客户正文。不能新增字段；所有身份字段固定，不能配置其他客户、设备、平台或账号。

| 字段 | 要求 |
|---|---|
| `schema` / `purpose` | `1` / `isolated-single-seo-publication` |
| `module` / `tenant_id` / `scope_id` | `seo` / `15` / `6` |
| `actor_id` | 当前实名顾问 `100007`，每次从当前用户、角色及原生顾问范围重新核查 |
| `device_id` | `0c764dd4-ebc0-45e9-912e-d46f7a42fc05` |
| `binding_id` | `a68a1fb9-af29-4b31-bb08-2f5d43bda3e5` |
| `account_id` / `external_account_id` | `acceptance-seo-gh-1864ed0c0506` / `gh_1864ed0c0506` |
| `platform` | `wechat-article` |
| `content_id` / `variant_id` | 实际当前已审母稿/渠道稿正整数 ID，数据库核对归属 |
| `source_revision` / `expected_digest` | 当前原生 `load_source` 的版本及中央 v1 内容摘要；不能自行声称已审 |
| `request_id` | 一份发布意图的唯一 UUID；整个流程保留不变 |
| `issued_at` / `expires_at` | UTC epoch 毫秒；当前时间必须在区间内，最多 30 分钟 |
| `expires_in_seconds` | 原生任务有效期 300–900 秒；签发时任务期限不能超过配置期限 |
| `task_id` | 创建前显式 `null`；实际原生创建成功后，由总控原子替换私有文件为响应中的唯一任务 UUID |

只有 `platform=linux-acceptance`、`production=false`、固定 WORK/cwd、loopback 55483 的独立 `distribution_acceptance_seo` 数据库、`acceptance_seo` 实际 schema 才可使用。验收工作目录须当前运行 UID 所有且无 group/other 权限。文件须当前 UID 所有、常规文件、私有权限（建议 0600）、单硬链接、最多 8192 字节；路径各级不可是符号链接，打开时 `O_NOFOLLOW` 并核对 inode/device。缺失、变形、重复 JSON key、过期均安全拒绝。文件不由代码写入，建议总控使用同目录新 0600 文件原子替换，禁止直接在 Git 中存真实配置。

## 放行路径

唯一任务创建请求为 `POST /api/distribution/v1/tasks`，JSON **严格只有**：

```json
{
  "module": "seo", "tenant_id": 15, "scope_id": 6,
  "variant_id": "取配置正整数", "binding_id": "取配置 UUID",
  "source_revision": "取配置版本", "expected_digest": "取配置摘要",
  "action": "publish", "confirm_reviewed_content": true,
  "confirm_manual_publication": true, "expires_in_seconds": "取配置整数",
  "request_id": "取配置 UUID"
}
```

以上说明中的字符串占位符不是有效请求。总控须在原生审核与渠道 ready 后签发配置。原生路由仍检查当前实名角色、顾问范围、active binding/device、真实已审来源、当前版本/正文素材摘要、项目 running/owner、排重，并事务化生成不同的 task grant 与 publication grant；本门禁不签发任一 grant。相同 request UUID 原生幂等重放只能返回原任务；配置绑定 task 后还核对该任务请求指纹、两 grant、lease 和全部目标元数据，不能切成另一任务。

绑定真实 `task_id` 后，允许顾问 100007 使用以下原路由，所有 scope、任务必须完全相同：

- `GET /api/distribution/v1/publication-source?module=seo&tenant_id=15&scope_id=6&task_id=<唯一任务>`
- `GET /api/distribution/v1/publication-monitor`，同上查询参数。
- `GET /api/distribution/v1/publication-assets/<唯一任务>/<合法素材ID>?module=seo&tenant_id=15&scope_id=6`
- `POST /api/distribution/v1/publication-check`，body 的 scope/task 固定；其他字段继续由原生 `PublicationCheck` 校验，人工模式仍须三个明确确认。
- `POST /api/distribution/v1/publication-writeback`，scope/task 固定，原生校验实际 event 与幂等请求。

公开 URL 校验继续使用原生固定平台、公网地址和完整公开内容检查；没有任意 egress URL 配置，不放宽 SSRF，也不修改严格 v1 回执白名单。`HUMAN_PUBLISHED` 仍只是人工报告，原生核验与成功回写后才成为交付记录；机器初步文本匹配不冒称完整页面/配图核验。

所有其他 `/publication-*`、`/publications` 写路径（manual/complete/sync/retry 等）、`/push` 均拒绝。编码路径、尾随斜线、重复查询 key、额外参数不能绕行。账号登录/核验 remote grant 与此入口分离，不修改 remote 的发布禁用规则。删除/过期配置关闭入口，但**不会假装取消已签发的原生任务**；停止在途执行须总控用原有 pause/revoke/短 grant 到期规则，未知结果保持 unknown，不能重发文章。

## 真实交付读取

只新增挂载原生 `list_content_publications` 的 **GET**，没有挂其写 handler：

`GET /api/v1/seo/content-distribution/publications?tenant_id=15&site_id=6&content_id=<配置母稿ID>`

此临时读取也受有效 permit 和真实 variant→content→tenant/site 核验；当前顾问或当前绑定 tenant15 且可读 SEO 内容的实名客户可读取，继续执行原生 scoped auth。原生接口读取实际 `SeoContentPublication`，不造 summary。它可能包含该母稿已有的原生发布记录；验收时须核对中央已回写的具体 `publication_id`/版本/公开链接，不能把旧记录当本次成功。

现成 `GET /api/v1/seo/workbench/content-assets/{content_id}/delivery?tenant_id=15` 保持原生鉴权与读取，不受短期发布 permit 影响。回写后母稿状态为 published，会返回 `workflow_status=published`；其 `result_basis.publication_status/page_check_status` 原生仍为 `not_loaded`，不是完整页面检查结果。公开链接/实际发布明细来自上述原生 publications GET；实际采集状态来自顾问 publication-monitor。permit 过期后临时 publications GET 关闭，不能声称这是永久生产交付读取改造，也不能将 pending capture 或未知收录状态解释为已采集/已收录。

## 定向验证边界

本地专项测试覆盖配置身份/类型/有效期/大小/编码/重复字段、精确任务请求、无确认或错误版本、路径与查询绕行、真实表字段形状的任务元数据核对、当前 binding 撤销、两种 grant 不可相同、原生只读路由挂载保留以及 ASGI 请求体重放到计数 sentinel。Linux stat/descriptor 测试在 Windows 上明确注入 OS 元数据，**不是实际云 Linux 权限验收**。数据库元数据校验为纯输入负例，不冒称真实 PostgreSQL/原生 JWT 联调。本批无服务启动、DDL、真实任务、平台请求或发布。

总控后续须在冻结源部署的独立 Linux 入口实际验证：无文件默认 deny、真实 0600/owner/path 边界、当前顾问 JWT、审核 ready/version、项目 running、唯一 publish task/双 grant、设备只领取此任务、一次真实发布、公开页核验、原生回写、当前客户/顾问读取和撤权/过期关闭。若发布结果不确定先核平台与原生任务，不能自动再发。执行端能力、账号身份、封面上传和平台最后提交由其受控流程负责，本脚本不称这些已验证。

# Tiger SEO GET-only 验收交接

目标是用已登录、已获授权的会话核对 `tenant_id=4` 的 SEO 生产数据准备情况。工具只发 GET，不包含登录、密码、令牌字面量、建站、采集、生成或发布逻辑。

## 文件

- `scripts/accept_tiger_seo_readonly.py`：生产 GET-only 验收脚本。
- `tests/test_accept_tiger_seo_readonly.py`：空站点、未配 GSC、无内容、无发布、跨租户拒绝和公开抓取来源标签的离线契约。
- `docs/SEO_TIGER_ADMIN_EXECUTION_RUNBOOK.md`：可直接交给管理员/真人的执行单、
  回传字段，以及 `empty_site` 后的查重和建站申请规范。

## 运行方式

生产验收当前为 `execution_status=blocked_until_merged`。必须先合并 PR #467，再从合并
记录取得并保存实际包含本修复的完整 main SHA，并按管理员执行单校验
`scripts/accept_tiger_seo_readonly.py` 的固定 SHA-256。任何一步未满足时不得运行以下
命令；PR 分支或创建 PR 时的旧 main 不能作为生产执行基线。

人工先用获准账号登录，再通过受控渠道把当前 Bearer 会话放入运行进程的环境变量。不要把令牌放在命令行、脚本、输出文件或聊天里。

```bash
export GSNIPERS_BEARER_TOKEN='<existing authorized browser session token>'
python scripts/accept_tiger_seo_readonly.py \
  --output tiger-seo-readonly-result.json
unset GSNIPERS_BEARER_TOKEN
```

脚本固定访问 `https://gsnipers.snipers.com.cn`、`tenant_id=4` 和
`tiger-coatings.cn`，不提供 CLI 覆盖。基础地址拒绝 userinfo、query、fragment 和
非默认端口；跨域重定向在转发 Authorization 前直接失败。

可选传入已有的公开网页预检文件：

```bash
python scripts/accept_tiger_seo_readonly.py \
  --public-preflight /controlled/path/tiger-public-crawl-20260908.json
```

该部分固定输出 `source=public_preflight` 和 `production_data=false`，不得将它作为生产 SEO 页面库、搜索表现或驾驶舱统计。

## 验收顺序

1. `/openapi.json`：实际指标 GET 必须挂载在 `/api/v1/seo/metrics/snapshot`。
2. `/api/v1/auth/me`：必须返回真实 `user` envelope；本脚本只接受绑定租户 4 的
   普通账号，且
   `seo.assets`、`seo.content`、`seo.site`、`seo.keywords`、`seo.dashboard`
   五项权限均为
   `view` 或 `edit`；缺少任一项时在模块、站点和数据探测前停止。脚本不会根据角色
   名称猜测授权，也不接受未绑定租户的超管会话代替普通账号验收。
3. `/api/v1/auth/modules`：SEO 必须 `available=true`。
4. `/api/v1/seo/sites?tenant_id=4` 与 `/api/v1/seo/workbench/sites?tenant_id=4`：
   先分别按目标域规范化匹配，再比较两表目标域是否同时存在及 site ID 集合；任一单向
   存在或 ID 集合漂移均输出 `status=site_unavailable`，之后才核对域名和状态。
5. 只有两表目标域匹配数均为 0 时才输出 `status=empty_site`，立即停止，不猜
   `site_id`。
6. `selection_policy` 必须精确为 `selectable_statuses=[active]`、
   `disabled_statuses=[paused, archived]`；顺序、缺项或额外状态发生漂移时，输出
   `status=site_unavailable` 并停止。站点为 paused/archived，或两份列表的
   ID/域名/状态不一致时，同样停止后续探测。
7. 恰好一个可选站点时，读取内容、发布、页面、GSC 配置和指标快照，输出 count / coverage / freshness。

空列表只证明该接口可读且当前无对象；不等于所有详情接口通过。`client_non_get_requests=0` 只证明客户端本次没有发送非 GET，不能单独证明服务端的 GET 永远无内部副作用。

## 待审查项

- 生产验收时会通过 OpenAPI 先确认 `/api/v1/seo/metrics/snapshot` GET 真实挂载；未挂载即停止。
- `content-distribution/publications` 目前没有分页参数，验收时会读取该站点全部发布记录；数量过大时应由 SEO 接口增加分页，不应由脚本猜参数。
- GSC 端点只证明连接配置；点击、展示、CTR 和平均排名仍应以指标快照的 source / observed_at / data_quality 为准。
- 单篇文章搜索点击仍不可由站点级 GSC 数据推算。

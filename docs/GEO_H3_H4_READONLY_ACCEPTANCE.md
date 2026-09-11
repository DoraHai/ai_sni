# GEO H3/H4 只读验收摘要

`GET /api/v1/geo/integration/read/content-tasks/{task_id}/acceptance-summary?tenant_id={tenant_id}`
只读取已经保存的母稿、审批、渠道稿、发布登记和发布页复查结果。它不会生成渠道稿、发布、
重新抓取、重试或修改状态。

返回的 `h3` 和 `h4` 分别包含系统已有证据、当前状态和仍需真人提供的证据。系统证据完成
只会把状态推进到 `awaiting_human_evidence`；接口不会把数据库里的发布登记当成渠道后台真实
文章数量，也不会把一次正文匹配当成登录页、错误页、空白页和五分钟缓存均已验收。

H3 真人证据固定为：渠道后台目标内容恰好一篇；重复提交一次后没有新增文章。H4 真人证据
固定为：真实公开页正文匹配；登录页、错误页和空白页均被拒绝；五分钟内重复检查复用已有
结果。回传时保留生产 SHA、任务/母稿/渠道稿/发布记录 ID、公开 URL、HTTP 状态、时间和截图，
不记录密码、令牌或渠道密钥。

调度器可观测性通过公开健康接口的 `scheduler_runtime` 和授权只读接口
`GET /api/v1/geo/integration/read/runtime-status?tenant_id={tenant_id}` 提供。`state` 明确区分：

- `active`：当前进程持锁并执行任务；
- `skipped`：内容调度锁由其他进程持有，当前进程不执行；
- `standby`：发布复查进程未持锁，等待接管；
- `stopped`：当前进程未启动该调度器。

每项同时返回 `owner`、`last_run`、`next_run`、`recent_failure` 和逐任务状态。由于进程锁不共享
运行历史，待机进程只能确认“其他进程持锁”，不会伪造持锁进程的最近运行时间。

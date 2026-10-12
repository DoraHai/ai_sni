# SEO 已核验发布结果回写（本地候选）

2026-10-11。本批独立于中央模块、工作台与生产迁移；没有发布平台调用、生产部署或生产建表。
入口固定为 `app.seo_distribution_results.record_publication`，不是客户端 HTTP 写入接口。

## 服务端调用与返回

```python
record_publication(session, actor_user_id, tenant_id, scope_id, variant_id, publication)
```

`scope_id` 为 SEO `site_id`，`variant_id` 为原生已审渠道稿。
仅中央已核验事件服务端调用；不能将客户端请求体直接转交此函数，也不能依靠
`verification` 字符串本身证明网页已发布。中央须完成 URL/内容/人工确认或机器证据核验。
原生适配器再次核验数据库身份、角色、当前网站顾问分配、租户、SEO 模块/网站状态、
母稿审核/客户确认、渠道稿审核和来源版本；正文、版本、平台及素材信息只从服务器读取。
不读取中央项目运行状态；中央项目 paused/ended 不妨碍接纳历史发布事实，但原生范围仍须有效。

`publication` 精确字段：

| 字段 | 约定 |
| --- | --- |
| event_id / task_id | UUID；事件幂等键 / 中央任务幂等键 |
| source_revision | 当前已审来源指纹；须与 load_source 完全一致 |
| content_digest | 中央 v1 有序内容元组的 SHA256；含来源版本、标题、正文和有序素材 manifest |
| platform | `wechat-article` 或 `xiaohongshu-image` |
| public_url | 规范 HTTPS 官方地址；微信 `/s/<id>` 或小红书 `/explore/<hex-id>`，不接 query/fragment/端口/短链 |
| reported_at | 原始回执 UTC epoch 毫秒 |
| verification | 仅 `human-verified` / `machine-verified` |
| verified_at | 核验 UTC epoch 毫秒，不早于 reported_at，允许最多 5 分钟时钟误差 |
| verified_by | 当前调用的实名顾问 ID；机器核验也保留触发核验的人 |

不接正文、账号凭证或额外字段；未核验、未知状态、跨范围、来源过期均拒绝。

中央保存/展示的统一返回白名单示例（数字仅为合成示例）：

```json
{
  "module": "seo",
  "publication_id": 101,
  "monitor_state": "pending",
  "verification": "human-verified",
  "idempotent": false
}
```

SEO 无独立 placement，省略 `placement_id`。函数另返回原生 `attempt_id`、
`page_check: {capture_id, state, reason}`、作用域、URL 和核验时间，用于原生证据关联与检查调度。
中央只保存上述白名单。`monitor_state` 是首次接纳时的检查预约状态，不是实时检查状态：
预约成功为 `pending`；渲染未启用为 `not_queued` 且 `reason=capture_disabled`。
重复回传 `idempotent=true`，其余返回保留首次接纳事实，不重复建立发布记录、尝试或检查。

## 事务与幂等

- 调用方提供干净的 READ COMMITTED AsyncSession 并控制提交；函数只使用 savepoint，不提交、不联网。
- 按事件 UUID 与任务 UUID 获取事务 advisory lock；首次写入还沿用原生 site→母稿→渠道稿行锁。
- 同 event 同载荷返回原结果；同 task 不同 event 且除 event 外载荷完全一致，只追加事件审计。
- 同 event/task 的 URL、身份、版本、核验方式、核验时间等出现矛盾，409 拒绝。
- 不同任务试图登记同母稿、同发布地址，409 拒绝，不接管现有手工或其他任务记录。
- 每次重试也重新检查当前权限、审核和来源；后续撤审/编辑不会删除历史记录，但旧事件不能再次被接纳。
- 失败回滚本次 savepoint，不保留半条发布记录，也不破坏调用方外层事务。
- SQL/存储故障返回 503 安全错误；无原始 SQL、连接信息或凭证回显。

## 原生发布、页面证据与搜索效果

1. 建立原生 `SeoContentPublication(status=published)`，关联 tenant、母稿、渠道稿、平台连接和规范地址。
2. 建立 `SeoPublishAttempt(action=central_verified,status=succeeded)`，保留人/机核验、实名核验人、事件/任务/版本/摘要。
3. 母稿进入 published，保留已有母稿主地址；多平台地址分别位于发布记录，不覆盖为单一地址。
   渠道稿继续保留 approved 的已审来源封印，避免破坏其他有效来源任务。
4. 同事务调用现有 `reserve_publication_page_capture`，检查直接关联到该发布记录。
   原生发布列表、发布清单导出及内容工作流因此可沿原关联读取；不直接将 SEO 工单改为 done。
5. **预约检查不等于执行检查**。调用方提交成功后，才能按 capture_id 调用现有
   `app.api.seo_page_captures.execute_page_capture`。本批不在事务中启动 worker。
   重启补偿可用 `pending_page_checks(session, actor, tenant, site)` 只读列出本适配器关联的待检查项
   （最多 50 条，当前作用域授权，不创建或更新任务），再交现有 worker。
   中央白名单不含 capture_id。后续本地候选已补原生周期调度、租约恢复及实时读取，
   详见 `SEO_PUBLICATION_MONITOR.md`；尚未部署，不代表线上已经开始自动抓取。
6. 现有 worker 继续负责公网 URL 校验、页面截图和失败记录；未执行、失败、人工上传与自动证据保持区分。
   只有真实检查完成后原生工作流才可评估交付证据，回写本身不标记页面通过。

`published_at` 暂使用 reported_at 转为原生 naive UTC；`link_discovery.time_basis=reported_at`
明确其为回执报告时间，**不是平台独立提供的精确发布时间**。
同一元数据与完整核验方式保存在尝试的 `response_summary`，既有尝试接口可读取。

SEO 当前没有可靠的单篇站外文章搜索收录监测链路；站点级搜索数据不能冒充文章收录/点击。
返回始终保留 `search_engine_indexed=null`、`indexation_state=not_measured`、`seo_effect=not_evaluated`。
发布核验、页面证据、搜索效果三者独立。

## 候选结构、验证与上线依赖

- `scripts/seo_distribution_results_schema.sql` 只提供候选事件审计表、索引、外键和禁止修改/删除触发器。
  尚未进入 Alembic 迁移链；运行时不自动建表，缺表时拒绝回写。
- 需数据库负责人审核候选结构，并按既有流程单独批准迁移、部署；本批不执行生产操作。
- 专项测试 `tests/test_seo_distribution_results_postgres.py` 使用专用 loopback PostgreSQL
  `seo_workflow_test` 随机 schema，结束清理；平台 HTTP 与检查 worker 在测试中禁止调用。
- 覆盖双方平台、人/机核验、当前权限/审核、伪造 URL/正文/版本/摘要、同事件/同任务并发、
  矛盾事件、不同任务撞地址、事务可见性/回滚、不可变事件、缺结构拒绝、原生清单与检查失败证据关联。
- 摘要算法与中央固定提交 `cb305e8580602569485e55588760cfbd94dc67fc` 的函数逐值比对；
  中央新核验服务通过 `tests/test_seo_distribution_results_broker_postgres.py` 动态加载实际模块和第三 DDL，
  真实 JWT、设备合成回执、3 项人工核验声明经真实 router 调用本适配器，不 mock 原生写入/审核/权限。
  覆盖 running/paused/ended、重复核验、当前审核撤回、结构故障与显式只回写重试、列表范围与脱敏。
  人工确认是合成测试数据，不能视为真实平台验收；页面检查只验证预约，不启动外网 worker。
- 最终中央版本已固定为 `729af3c4071d6f410ef12ecb88de6ca6a3559f13`，6 项实际回写联调
  通过 `SEO_DISTRIBUTION_ROOT_COMMIT` 从该提交读取所有中央模块及 3 份 DDL；不依赖后续工作区变动。
  中央静态页面内容匹配只属机器初检 needs-human，本次合成用例走人工 3 项核验，未调用真实平台。

## 本轮结果

SEO 干净代码提交 `3cf2ddb9892eb5c0dca7db6510e2459d9c0e7ba9` 合跑 **232 项通过、0 失败、0 跳过**，
含 52 项原生回写专项、6 项实际中央回写联调、19 项既有中央来源/设备联调、
25 项素材 PG、1 项 Chromium、53 项来源、56 项分发、17 项客户确认、3 项发布清单测试。
3 条警告为依赖弃用提示。报告及逐文件指纹见 `SEO_DISTRIBUTION_RESULTS_EVIDENCE.json`。

最初 232 项合跑使用中央工作区的加载快照，其后中央继续修改，因此原始指纹及结果保存在
证据 JSON 的 `prior_working_tree_run` 中，避免把早先全量回归冒充最终版本回归。

中央冻结后已按最终提交 `729af3c4071d6f410ef12ecb88de6ca6a3559f13` 单独复跑实际回写联调：
**6 项通过、0 失败、0 跳过**，1 条依赖弃用警告。受测 SEO HEAD 为
`6f73851b`（业务代码仍为 `3cf2ddb9`，所有原生代码/DDL/测试 blob 摘要未变），测试时工作区干净。
最终中央逐文件 SHA256、报告摘要和 6 项业务结果已归档；本轮只更新文档和证据，未重复运行其余测试。
测试仅在 `127.0.0.1:55443` 专用数据库的随机 schema 中运行并清理，没有停止共享 PostgreSQL 服务。

# SEO 经营驾驶舱对接基础

本模块仅提供任务及指标接口，不连接驾驶舱、不接收跨模块执行命令。任务和指标始终由 `tenant_id`、`site_id` 限定，沿用登录态/服务端密钥、SEO 开通校验和菜单权限。API 前缀为 `/api/v1/seo`。

## 共享字段

任务返回 `id, module, action_type, title, params, status, created_by, assignee_role, completion_evidence, created_at, updated_at`。`module` 固定 `seo`；状态仅 `open / in_progress / done / cancelled`；时间为 UTC ISO 8601。创建人由鉴权身份确定，用户不能冒用别人的 ID；无用户 ID 的服务端密钥创建人记为 `cockpit`。`assignee_role` 只是分派标签，不授予权限。

指标快照直接返回列表，每项仅包含 `metric_key, value, unit, as_of, trend_7d`。无可用观测的数值为 null。

`trend_7d` 严格为 null 或下列对象：

```json
{"direction":"up","change_pct":25.0,"change_abs":2.0}
```

方向仅为事实性 up/down/flat，不代表好坏；与七天前相比，绝对变化为当前减历史，百分比为绝对变化除以历史绝对值乘 100。历史基数为零时百分比为 null，绝对变化及方向仍按事实填写。历史不足七天或任一数值不可用时整个对象为 null，不填零。历史由独立调度每小时采集，取七天前及此前两小时以内最近一条；不跨长期缺测回填。读取快照不写入历史、不调用外部供应商。

## 任务 API

- `POST /tasks`：创建。正文包含 tenant_id、site_id、action_type、title、params、assignee_role，可传 module=seo、created_by（必须匹配身份）。初始状态 open，不允许客户端提交完成证据。
- `GET /tasks?tenant_id=…&site_id=…`：分页列表，支持 status、before_id、limit（1–100）。仅返回当前角色有权访问的行动类型。
- `GET /tasks/{id}?tenant_id=…&site_id=…`：读取契约及证据。
- `PATCH /tasks/{id}`：更新 title、assignee_role、status，正文必须包含 tenant_id、site_id。完成时由服务端重新查指标及关联记录，调用方不能自行填写证据。
- `DELETE /tasks/{id}?tenant_id=…&site_id=…`：取消任务并保留审计记录，已完成任务拒绝删除。

支持的 SEO 行动类型：`content_review`（params.content_id，内容权限）、`image_repair`（params.review_id，站内优化权限）、`ranking_improvement`（关键词权限）。参数仅作为关联数据保存，不作为 SQL、URL 或脚本执行。任务结束后不可改写。

现有 submit-review 会建立或复用内容任务，review 批准推进 in_progress、退回保持 open；审核通过不直接完成。内容任务完成需关联文章在任务创建后实际进入 published，且七天发布篇数较创建基线增长；图片任务需关联审核方案在任务创建后重新抓取确认且确认数量增长；排名任务需核心词前十数量增长。无基线或无指标增长返回 409。证据保存基线、完成时数值、变化量、时间和关联内容/图片快照，不保证业务因果关系。滚动窗口内若同时有其他文章移出窗口，净增长可能不足，此时不误报完成。

## 指标 API 与口径

`GET /metrics/snapshot?tenant_id=…&site_id=…` 返回指标列表；需同时拥有关键词、内容和站内优化读取权限。`GET /metrics/definitions` 返回每项的一句话口径。

| metric_key | 单位 | 口径 |
|---|---|---|
| seo.ranking.top10_keyword_count | count | 当前网站启用的 P0/P1 核心词，按百度桌面全国自有域名最新七天内观测去重，排名 1–10 的词数；无观测返回 null。 |
| seo.content.published_7d_count | count | 当前网站过去 7×24 小时内发布且当前为 published 的内容资产去重篇数，多平台分发不重复计数。 |
| seo.images.verified_repair_count | count | 当前网站未被替代的审核方案中，重新抓取唯一匹配原图并确认审核方案已应用的数量。 |
| seo.images.pending_repair_count | count | 当前网站当前审核方案中尚未获重新抓取确认的数量，包含待核实、未生效、抓取异常。 |
| seo.images.repair_completion_rate | percent | 重新抓取确认数÷当前已进入核实流程且未被替代的审核方案数×100；没有方案返回 null。 |

图片分母是已审核整改方案，不是全站全部图片或全部未审核候选。历史 approved 不自动当作完成；本版本开始保存审核时进入核实流程。新审核替代同一页面同一图片的旧方案，不重复计数。

## 图片核实

保存审核方案后，审批记录与 pending 队列在同一事务提交。调度每分钟最多处理 10 项，复用 collect_page_snapshot / save_page_snapshot（robots、公网地址防护、单页 40 秒超时），不下载图片、不改客户网站。

状态为 pending → checking → verified / unverified / unavailable；旧方案为 superseded。租约五分钟，服务重启后可重取过期任务；旧审核结果不能覆盖新方案。

内容图要求前后快照中原图地址均唯一出现，且新非空 Alt 与已审核文本一致；装饰图要求从缺失/空白字符变为明确空 Alt 且不在链接内，原本已经为空的 Alt 不算一次修复。原图消失、替换、重复、观测截断、抓取失败均不算完成。旧版本快照只有问题图片列表，不能排除同地址的正常图片重复，此时返回不可核实，需重新检测并审核，不凭缺少证据推断完成。结果保存审核 ID、前后快照 ID、实际 Alt 和判定原因；被引用的新快照不会被保留期清理删除。

`GET /image-verifications?tenant_id=…&site_id=…` 查询中间状态及证据。`POST /image-verifications/{id}/retry?tenant_id=…&site_id=…` 在网站实际应用修改后重新排队，仅未生效/异常任务允许，上次检查后至少五分钟。审核批准本身不代表修复。

## 数据库及故障修复

新增迁移 `0092_seo_cockpit`，仅新建 seo_tasks 与 seo_image_verifications，不改 SEM/GEO 表。生产迁移应与应用部署分开备份、验证，不将 upgrade 隐藏在应用发布中。

生产基线已存在排名租户独立会话和回滚失败隔离，保留并回归验证；发布异常兜底补充不确定结果/人工介入标记。此基线规则引擎只有一个 keyword upsert，补齐 status/priority/campaign 刷新，不移植 SEM 的实体模型和索引。租户参数解析段直接移植 SEM 的 int/float/str 校验和多来源一致性检查，不包含 SEM 专有授权逻辑。

## 本轮验证

四项故障相关定向回归先执行，79 项通过。完整 SEO 后端与相关共享测试在新建隔离 PostgreSQL 数据库下 768 项通过，无跳过；后续证据匹配及 OpenAPI 契约补充后定向 192 项通过。前端 49 项、任务中心/诊断/整改组件检查、正式构建及 49 个产物校验通过。新增数据库测试覆盖租户隔离、实际指标增长后完成、审核任务状态复用、七天趋势、审批后核实与过期租约恢复。手工指标接口禁止伪造 cockpit_observation 历史。网络抓取使用模拟响应，未修改客户网站或调用第三方发布。

共享趋势格式和图片核实口径已按用户要求同步给 SEM、GEO 任务留档。本轮仅完成基础设施，不对接驾驶舱；生产 migration=not-run。

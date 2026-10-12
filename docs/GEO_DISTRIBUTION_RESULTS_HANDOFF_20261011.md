# GEO 经核验分发结果回写（本地候选，2026-10-11）

已新增只读的原生最新监测状态接口，见
[最新监测状态投影](GEO_DISTRIBUTION_MONITOR_STATUS_HANDOFF_20261011.md)。它读取当前原生状态，
不再依赖首次回写返回的 pending 快照；本批原生回归 100 项通过，中央冻结版实际 GET/原生回写
联调 10 项通过（新监测场景 3 项、必要回写回归 7 项）。仍未部署或读取真实平台。

后续中央真实 JWT/router/PG 联调已补齐，见
[中央与原生回写联调](GEO_DISTRIBUTION_PUBLICATION_BROKER_20261011.md)：7 个新增场景及完整
72 项回归通过。本文下方的 65 项统计与“尚未做中央联调”描述保留为首次原生 adapter 交付历史；
当前联调边界和逐文件 SHA256 以新文档及对应证据 JSON 为准，仍未上线或操作真实平台。

本批只补 GEO 原生结果回写，不修改中央、原程序、SEM、生产迁移链或部署入口。
中央完成真实顾问授权、历史发布结果核验后，通过固定服务端适配器调用；不新增接受客户端正文或审核状态的 HTTP API。

## 固定服务端接口

```python
from app.geo.distribution_results import record_publication

result = await record_publication(
    session, actor_user_id, tenant_id, scope_id, variant_id, publication
)
# 调用方继续写中央核验/回写记录，最后统一 commit。
```

`publication` 严格只接受：

- `event_id`、`task_id`：UUID 字符串。
- `source_revision`、`content_digest`：原任务的审核版本与完整内容摘要。
- `platform`：`wechat-article` / `xiaohongshu-image`。
- `public_url`：规范官方 HTTPS 链接。微信 `/s/<id>`，小红书 `/explore/<lowercase hex>`；不接受跳转短链、用户信息、非标准端口、查询串、片段或控制字符。
- `reported_at`、`verified_at`：epoch ms；后者不早于前者。
- `verification`：`human-verified` / `machine-verified`。
- `verified_by`：必须等于本次当前实名顾问 ID。

```json
{
  "module": "geo",
  "publication_id": 1,
  "placement_id": 1,
  "monitor_state": "pending",
  "verification": "human-verified",
  "idempotent": false
}
```

返回数据只含结果 ID 和状态，不含正文、凭证、账号 Cookie 或图片字节。
函数不调用 commit，不抓取公开页面。内部 savepoint 确保异常后，调用方即使提交中央失败状态，也不会残留部分原生发布记录。

## 授权、版本与幂等

首次及重复调用均复用 `load_source`：当前客户 GEO 服务、实名账号/角色权限、项目业务范围、顾问分配、最新母稿/渠道稿、客户审核、品牌事实与发布规则门禁仍全部生效。分发项目暂停/结束本身不在此适配器新增执行门禁；原生项目/服务授权门禁继续生效。

首次回写严格比较 `source_revision` 和 `content_digest`。摘要算法逐项与中央 `distribution_contract.content_digest` 一致，包含图片的顺序、ID、SHA256、类型和长度。

独立账本：

- `geo_distribution_publications`：`task_id` 主键，保存审核版本、摘要、规范 URL、原生 publication/placement ID。
- `geo_distribution_publication_events`：`event_id` 主键，保存人核验/机核验、核验人、登记/核验时间及完整 payload 摘要。

同事件的不同 payload、同分发任务的不同客户/项目/渠道稿/审核版本/摘要/平台/URL 均冲突。相同任务的新核验事件复用同一原生结果，新增核验历史，不重复创建 publication、placement 或监测入口。任务行锁及按固定顺序取得的事件/任务/布局 advisory locks 覆盖并发。

原生发布和监测会更新 `variant.updated_at`。重复调用不能因此误判；它仍核验最新门禁与实际 title/body/assets 身份，并与账本内原任务身份比较。正文/图片被改、撤审、最新母稿被替换、权限/服务/分配变化均拒绝重复回写。原生发布 URL/status 或布局被修改同样要求人工核查。

两张账本都有追加审计触发器，禁止更新/删除。其外键也保留经核验结果与原生对象的关联，硬删除原生对象需另行处理审计保留规则。

## 原生工作流与真实含义

复用现有 `_write_publication` 最终审核门禁、`GeoPublication`、当前优化周期与 `_sync_task_pipeline`。复用已存在的相同渠道稿+URL 发布记录与相同 prompt+URL 布局，不覆盖原人工记录。

新增 `GeoMediaPlacement` 标为已发布，但 `citation_national` 保持空，说明权威度与 AI 引用尚未评估。没有把一次发布伪造成 AI 曝光/引用。

监测使用已有 `publication_monitor`，初始 `pending`。已存在的实际监测结果保持不变。人核验/机核验登记不直接写成 `healthy`，后续真实监测仍分别报告可访问性、内容匹配或版本变化。原生 `list_monitor`、项目范围的报告 `_evidence` 和 `citation_rows` 已在真实 PG 验证能读取本次结果，未有真实引用样本时 exact/loose 引用数均为 0。

`published_at` 采用 `reported_at` 的 UTC 登记时间，记录 note 明确它不代表平台首次发布时间；当前协议没有平台真实发布时间字段。优化周期沿用原生任务归属，不伪造平台日期。

## 文件与本地数据库

- `app/geo/distribution_results.py`
- `scripts/geo_distribution_results_schema.sql`
- `tests/test_geo_distribution_results_postgres.py`
- 本文及 `docs/GEO_DISTRIBUTION_RESULTS_EVIDENCE_20261011.json`

独立 SQL 为本地候选：两张新增表、索引和追加审计触发器，没有修改原有表或生产迁移链，不在运行时执行 DDL。上线需审阅并组装到正确 GEO 基线；本批未执行生产建表。

验证使用独立 PostgreSQL `127.0.0.1:55507`、数据库/用户 `geo_ci`；测试同时断言 driver/host/port/database/user，禁止使用其他库。每个数据库场景创建随机 `geo_results_test_<32 hex>` schema，结束删除；独立 DDL 已测试重复执行。临时数据目录位于系统 TEMP，未触碰生产或共享 55443 实例。

## 验证结论与边界

2026-10-11：**65 passed，0 failed，0 skipped**。

- 34 个本批测试：18 个真实 PG 场景（真实事实卡、审核、门禁、事务/并发/监测/报告）及 16 个合同/URL/摘要检查。
- 回归：8 个原生来源 PG 场景、1 个最终发布门禁、22 个原生监测单元测试。部分旧回归含明确测试替身；本批真实 PG 授权/发布规则正常路径没有 mock 门禁。
- 覆盖：人/机核验区分，未知/仅人工报告拒绝登记，跨客户/错渠道稿/假核验人，撤审/角色/顾问/服务/母稿/正文改变，版本/摘要/图片错误，官方 URL，6 并发幂等，新事件同任务不重复，回滚和注入原生 flush 后故障的 savepoint，追加历史禁止删除，复用原生记录及报告/监测衔接。
- XML：系统 TEMP `geo-distribution-results-20261011.xml`。
- XML SHA256：`529cc7fce4165e20715aa6574df0ed9963e6787f893b1b3e87ce774fe3c919c0`。

**尚未做**：生产 DDL/部署、中央真实 JWT 核验端到端联调、真实平台公开页抓取、编辑器自动填稿/上传或最终提交、设备真实账号凭证提取。中央集成须在正确 GEO 基线上加载本文件与 DDL；不能把旧中央模型基线整个覆盖 GEO。

SEM AI 接管仍关闭，按用户要求最后推进。

# GEO 完成稿候选接口（2026-10-12，本地）

从 `354997853ee518a2cbe4cc66841818968a19fea4` 接续。仅新增原生 GEO 来源适配器的两个只读
元数据接口、测试和交接证据；不改中央、共享鉴权/main、SEO、多号通、SEM、DDL 或监测 worker。

## 中央装载接口

```python
from app.geo.distribution_sources import list_intake_candidates, load_intake_candidate

page = await list_intake_candidates(
    session, actor_user_id, tenant_id, scope_id, platform,
    after_variant_id=None, limit=50,
)
current = await load_intake_candidate(
    session, actor_user_id, tenant_id, scope_id, variant_id, platform,
)
```

`platform` 沿用 `wechat-article`、`xiaohongshu-image`。列表严格只有 `items` 和 `next_cursor`；
每项严格只有以下五个字段，点查询返回同一项或 null：

```json
{
  "variant_id": 91,
  "draft_version": "geo-draft-v1-opaque_content_digest",
  "source_revision": null,
  "readiness": "awaiting-review",
  "reason": "geo_distribution_review_pending"
}
```

实际 draft_version 是固定前缀加 SHA256，不返回上述示意摘要。版本字段符合 1–100 位
`[A-Za-z0-9_-]`，reason 为固定 ASCII 枚举，符合 1–64 位 `[A-Za-z0-9_]`。
不返回标题、正文、图片、素材清单、URL、文件路径、错误原文或凭据。

列表只取项目当前 business/prompt 归属内的指定渠道最新 variant，最新排序与 load_source 一致：
`updated_at DESC NULLS LAST, id DESC`。先确定最新，再过滤完成状态，不能退回旧成稿。
variant 完成状态为 `draft/exported/published`；任务处于 `generating/adapting/archived/cancelled`
时不进入完成稿集合。返回按 variant_id 升序，仅 ID 大于游标，limit 严格为整数 1–50。
查询多一条判定后续页；有后续页时游标为本页最后 ID，末页为 null。
中央每轮扫描一页，结束后从头扫描，才能拾取旧 ID 的审批变化。

点查询先执行当前身份/范围授权，只在 ID 不存在、不属于该 scope/platform 最新版本或非完成稿
集合时返回 null。仍然最新的待审、待适配稿返回元数据，不误当失效稿。
点查询复用 limit=1 的分页与同一门禁逻辑，并严格核对返回 ID。

## 状态与版本

| 当前原生情况 | readiness / reason |
| --- | --- |
| 尚未提交审核 / 待审 / 退回 / 非法审核状态 | awaiting-review / review_not_submitted、review_pending、review_rejected、review_invalid |
| approved 但无有效审核人员/时间或审核早于母稿 | awaiting-review / review_invalid |
| 母稿已更新、标题/正文不完整、适配明确未就绪或元数据坏结构 | awaiting-adaptation / master_stale、content_empty、adaptation_pending、adaptation_invalid |
| 实际发布规则/事实门禁不通过，或素材缺失/清单不一致 | awaiting-adaptation / publish_gate_blocked、assets_unavailable、asset_manifest_invalid 等现有固定代码 |
| 现有 load_source 完整通过 | ready / source_ready，source_revision 严格等于其返回值 |

表中 reason 均带 `geo_distribution_` 前缀。等待项 source_revision 为 null。
ready 不是发布授权，中央仍需重新调用 load_source 并执行当前控制、渠道、审核、版本与分发门禁。
原有 list_sources/load_source/素材审核代码不变。

draft_version 仅散列实际渠道稿标题、正文、channel 与发布素材顺序/媒体类型/实际字节摘要。
不包含审批状态、审批人/时间、母稿 ID、variant 更新时间、图片记录 ID、监测或发布元数据。
待审→批准更新同一意图；正文、标题或实际图片内容变化才变版本。审批与监测时间变化仍可能
改变 source_revision，中央必须更新同一队列项的审核快照。
纯公众号通路不发布图片，既不散列图片，也不查询可选图片表，保留分阶段安装兼容性。
小红书缺少可选素材表是数据库故障，明确 503，不能转换为等待适配或 null。

## 事务与调用边界

调用方使用短 READ COMMITTED 事务，不与已经 flush 或 SQL 写入原生身份/稿件/事实/素材的事务
混用；原生编辑须先提交或回滚。中央 scan_channel 每渠道新会话，仅写中央配置、queue 和日志，
不写 native，因此符合这个约定。此接口不是通用的混合原生写入事务读取器。

接口使用调用者同一实际 connection，并建立临时独立 identity-map、autoflush=False 的
AsyncSession，`join_transaction_mode="create_savepoint"`。读保存点关闭时仅回滚自身保存点，
不 flush、不覆盖调用者 dirty/new 对象，不 commit、不回滚或关闭调用者外层事务。
单连接池、已有 tenant/task 锁、引擎的随机 schema/search_path 都继续可用，没有第二连接需求。
现有 authorize_scope 和 load_source 会 SELECT FOR UPDATE，因此这里的“只读”是无数据修改，
不是 PostgreSQL `SET TRANSACTION READ ONLY`。

读保存点设置局部 lock_timeout=3 秒、statement_timeout=15 秒；正常返回、SQL 故障和 Python
取消后均恢复调用者设置。结构、SQL 和服务 5xx 故障只抛固定 sanitized 503。
失权/范围拒绝保留异常；原生助手包装在 409 中的 401/403/5xx 原因不会被吞成等待适配。
没有 xmin/pg_xact_status 或其他系统函数探测，没有新增 PostgreSQL 最低版本要求。

## 验证与真实平台边界

原生代码冻结提交：`bb996007e352e2eff5f893da985cb07f63e907f5`。
最终回归 **86 passed，0 failed，0 skipped**：32 个新增原生 PG/JWT 场景、原生结果回归 34、
来源 PG 回归 8、最终发布门禁回归 1，以及实际中央联调 11（新增队列 1、原回写/monitor 10）。

随后从中央固定提交 `f5ed86697c4e8c3ce8d4854d888dcf5090064368` 通过本地 `git show` 提取
11 个运行代码/DDL 文件到全新系统 TEMP 目录，再装载这些冻结文件执行必要联调，
**11 passed，0 failed，0 skipped**。这是上述 11 项的冻结源码复验，不另算 11 个独立场景。
没有继续依赖中央正在编写文档的工作树；冻结文件摘要逐项记录在证据 JSON。

- 回归 XML：系统 TEMP `geo-distribution-intake-final-20261012.xml`。
- SHA256：`d7a61f84aecb9627c9566ab627befffdd10b64f2d6e33337c8fb0835c7771177`。
- 冻结中央 XML：系统 TEMP `geo-distribution-intake-broker-frozen-f5ed8669-20261012.xml`。
- SHA256：`5de6d011fc203a6cd18865e48a81a4b3835be2b0460c24f1714e730f2bfecee7`。

测试结果、XML 摘要、本地运行文件摘要及中央实际装载快照见同目录
`GEO_DISTRIBUTION_INTAKE_EVIDENCE_20261012.json`。

新增原生场景使用真实 PostgreSQL 身份、当前归属、审核、事实及素材，未 mock 正常授权或门禁。
只有服务 503 故障和 Python 取消场景注入故障/延时；原有来源与发布门禁回归保留其明确测试替身。
覆盖 122 个完成稿分页、末页游标、旧 ID 审批变化、跨租户/真实第二项目、真实 JWT 与撤权、
审批稳定版本、正文/实际图片变版本、最新生成中不回退、pool_size=1、脏对象保留、已有锁、
调用者 SQL/事务保留、异常/取消恢复 timeout、冻结历史行和可选素材表缺失。

实际中央 router/JWT/PG + distribution_queue.scan_channel/run_once 联调验证：待审稿进入已配置
渠道队列；批准沿用原队列 ID；正文改版、新渠道稿替代后旧项 superseded；点查询使没有
source_revision 的旧 pending 项也能失效。队列扫描未生成设备任务、发布保留或原生发布记录。

仅自有 `127.0.0.1:55507/geo_ci` 随机 schema；不使用共享 55443。中央装载需现有 control、
scheduling、publication、queue 四份候选 DDL，但本批没有对生产安装。原生纯公众号无需新表，
小红书素材沿用原先可选 GeoChannelAsset 表。没有联网、浏览器操作、真实发布、GitHub 操作、
部署或 SEM AI 接管。

最终随机 schema 剩余 0，自有 55507 已停止，共享 55443 未连接或停止。
验证运行时为 PostgreSQL 16.15、SQLAlchemy 2.0.36；没有新增包或版本依赖。

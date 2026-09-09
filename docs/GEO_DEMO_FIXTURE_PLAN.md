# G-Snipers 全域演示：GEO 离线夹具方案

## 目标与当前边界

本方案为独立的“G-Snipers 全域演示”租户准备可重复、全虚拟、显著标识的数据包。它不使用老虎
tenant 4、诺德 tenant 1 或任何现有客户数据。当前实现只有确定性离线清单和校验器，没有数据库
写入入口，不调用模型、巡检、内容生成或发布，也不修改生产配置。

```powershell
python -m app.geo.demo_fixture_manifest validate
python -m app.geo.demo_fixture_manifest digest
python -m app.geo.demo_fixture_manifest plan > geo-demo-plan.json
```

`plan` 只把 JSON 写到标准输出；模块没有 `apply`、`seed` 或 `delete` 命令。默认完整周结束边界为
2026-09-07 周一 00:00（Asia/Shanghai），覆盖 2026-08-24 至 2026-09-07 两个完整自然周。

## 模型与正式指标准入审计

正式指标 `/api/v1/geo/integration/metrics/snapshot` 的现有准入链为：

1. 非品牌点名问题；
2. `sample_mode=openai_compat` 且 `simulated=false`；
3. `method=unprimed_json_v2`、`analysis=completed`，引用没有标为不准确；
4. 回答必须和同租户、已完成服务端巡检的原始 cell 在问题、引擎、正文、提及、竞品和引用上完全一致；
5. 每个完整周至少 8 条、3 个问题、2 个引擎；
6. 环比还要求前后周问题、引擎、供应商、模型及每格样本数完全一致。

夹具的 72 条回答全部同时设置：

- `sample_mode=mock_persona`
- `simulated=true`
- 正文和备注包含 `[全虚拟演示][GEO_DEMO_FIXTURE:g-snipers-geo-demo-v1]`
- `formal_metric_eligible=false`

因此逐条回答在只读详情中显示 `simulated_sample` 和巡检不符合正式准入的排除原因；正式指标的三个
值及 `trend_7d` 均为 `null`。期次接口显示合格样本、问题和引擎不足；可见度分数还显示没有启用
官网域名。清单另带 `demo_only_raw_comparison`，用于演示两周原始样本差异，但明确标记为
“illustrative synthetic values; never official metrics”，不能替代正式指标接口。

## 对象数量

| 对象 | 数量 | 用途 |
| --- | ---: | --- |
| 独立租户 | 1 | 名称为“G-Snipers 全域演示（全虚拟）”，物理 ID 尚未分配 |
| 品牌业务 / 优化单元 | 1 / 3 | 演示品牌画像和业务层级 |
| 问题 | 12 | 非品牌点名的中文选型、运维和知识管理问题 |
| 引擎 | 3 | DeepSeek、通义千问、Kimi；带供应商和历史模型名，全部禁用 |
| 完整优化期次 | 2 | 前一完整周和当前完整周 |
| 虚拟巡检 / 回答快照 | 2 / 72 | 每周 12 题 × 3 引擎，全部模拟 |
| 发布渠道 / 账号 | 3 / 0 | 官网、微信、知乎；渠道禁用且没有账号 |
| 事实卡 | 6 | 产品、指标、案例各两条，均标记虚拟且 `needs_review` |
| 内容任务 / 母稿版本 | 2 / 4 | 分别展示旧稿失效与三渠道稿已重生成 |
| 渠道稿 / 发布记录 | 6 / 0 | 每任务三渠道；全部 draft、不可发布 |
| 待办 | 4 | todo 2、doing 1、cancelled 1；没有 done 和伪造完成证据 |

前一周有 36 条模拟回答、12 次虚拟品牌提及；后一周有 36 条、18 次虚拟提及。清单提供提及数、
提及率、官网虚拟引用数和三家虚拟竞品的演示环比。正式指标仍必须返回 null。

## 状态场景

`content_task:invalidated` 有 V1/V2 两个母稿版本，当前审核为 `none`，三个渠道稿仍绑定 V1，
期望只读显示 `stale=true`。`content_task:regenerated` 同样有 V1/V2，三个渠道稿已经绑定 V2，
期望 `stale=false`。两组渠道稿均为 `draft`，正文含全虚拟标识，`publishable=false`。

待办不制造“已完成”状态。全虚拟数据无法提供任务契约要求的真实指标变化，因此
`completion_evidence` 均为空；取消项无需完成证据。这样可以演示待办、负责人和基线位置，同时不会
把自行勾选或模拟指标伪装成完成。

## ID、幂等与隔离策略

所有对象使用全局唯一逻辑键：

```text
g-snipers-geo-demo-v1:<object_type>:<name>
```

清单不指定数据库主键。现有业务表也没有统一的 `logical_key` 列，因此不能仅靠名称可靠地重复加载。
未来加载器必须通过获批的 GEO 夹具登记表，用 `fixture_namespace + logical_key` 解析物理 ID后 upsert；
外键只通过登记表绑定，禁止硬编码 tenant 1、tenant 4 或任何已有 ID。重复执行同一版本只能更新本
命名空间对象，不得增加行数。加载前后都要断言：

- 新租户物理 ID 不等于 1 或 4；
- 每个 GEO 子对象的 `tenant_id` 都等于新租户 ID；
- 不存在跨租户 prompt、business、period、fact、task、snapshot、variant 或 ticket 外键；
- 老虎 tenant 4 和诺德 tenant 1 的各表行数、更新时间和内容摘要保持不变。

## 只读接口可见性

加载后计划从以下现有接口读取，不新增工作台专用汇总逻辑：

- `GET /api/v1/geo/integration/read/questions`
- `GET /api/v1/geo/integration/read/answers` 及单条详情
- `GET /api/v1/geo/integration/read/period-context`
- `GET /api/v1/geo/integration/read/capabilities`
- `GET /api/v1/geo/integration/read/content-tasks/{id}`
- `GET /api/v1/geo/integration/read/patrol-runs/{id}`
- `GET /api/v1/geo/integration/metrics/snapshot`
- `GET /api/v1/geo/integration/metrics/dictionary`
- `GET /api/v1/geo/integration/tasks`

回答列表展示虚拟原文、问题、引擎、供应商、模型、明确时区、提及、虚拟引用、竞品、来源分类和
排除原因。正式周指标只展示 null 及样本不足原因；工作台不得从回答列表自行汇总正式指标。

## 调度与执行隔离

清单把巡检设置设为 `enabled=false`、`auto_persist=false`、`prefer_real=false`、`prompt_limit=0`，
三个跟踪引擎全部 `enabled=false`，AI 设置 `enabled=false` 且无密钥。三个发布渠道全部禁用，账号和
发布记录为空。

这些配置能阻止当前定时巡检选中租户，也能让当前发布前置条件失败，但不能形成“永久不可执行”的
安全边界：管理员以后仍可能修改开关或配置账号；夜间 daily metrics 重建也会扫描存在回答的租户。
因此数据库写入保持禁用，直到下面的持久标识和门禁获批。

## 回滚与清理草案

未来加载器必须在单事务中完成 upsert，并记录每个逻辑键解析出的物理 ID。清理同样使用单事务，
先复核租户名、fixture namespace 和所有行的虚拟标记，再按以下顺序删除：

1. 发布记录（预期始终为 0）、渠道稿、母稿、任务事实关系、内容任务；
2. 待办、回答快照、虚拟巡检、期次；
3. 事实卡、问题、优化单元、优化业务；
4. 渠道账号（预期 0）、发布渠道、跟踪引擎、巡检和 AI 设置；
5. GEO 开通关系及独立演示租户。

任何目标行缺少 namespace、出现非虚拟发布记录、存在未知外键或租户 ID 为 1/4 时，清理必须拒绝
执行并整单回滚。禁止使用“按日期”“按 ID 范围”或模糊租户名称清理。

## 数据库负责人需确认

正式实现加载器前，需要数据库和共享身份负责人明确以下事项：

1. 为独立租户分配物理 ID和 GEO module entitlement；确认不复用 tenant 1、tenant 4 或已有测试租户。
2. 选择持久演示标识和幂等登记结构。运行时只读契约要求一张不可变回执表：
   `public.geo_demo_fixture_registry(tenant_id PK/FK, dataset_key UNIQUE, dataset_version,
   fixture_namespace UNIQUE, manifest_sha256, status, loaded_at)`，其中完成装载的状态只能是 `sealed`；另推荐
   一张 GEO 自有对象登记表：
   `geo_demo_fixture_objects(fixture_namespace, logical_key, table_name, object_id, payload_hash, created_at,
   PRIMARY KEY(fixture_namespace, logical_key), UNIQUE(table_name, object_id))`。若采用共享
   `tenants.is_demo`，需由跨模块负责人统一迁移，GEO 不自行修改共享表；对象登记仍需保留。
3. 获批的标识必须被巡检创建/执行、定时巡检、daily metrics 重建、内容生成、渠道稿生成、客户审核、
   publication/push/push-batch 和发布回填入口共同拒绝；只读接口继续允许访问。
4. 正式指标需保留现有逐条模拟排除，同时增加租户级演示排除作为纵深校验；即使有人误把快照改为
   `openai_compat` 或 `simulated=false`，演示租户也不能进入正式指标。
5. 确认加载器服务账号只能写该演示租户的 GEO 表，并批准 child-first 清理顺序和审计留存周期。

上述五项没有全部确认前，不提供数据库 apply/cleanup 命令，不在任何环境落库。

## 测试

`tests/test_geo_demo_fixture_manifest.py` 验证：清单完全确定、逻辑键唯一、对象数量固定、完整周边界、
72 条回答全部显著标记模拟、现有正式样本判断全部排除、正式指标预期为 null、演示环比正确、巡检/
引擎/渠道关闭、账号和发布为空、待办没有伪造 done，以及非周一边界会被拒绝。

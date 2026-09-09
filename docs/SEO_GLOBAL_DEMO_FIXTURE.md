# G-Snipers 全域演示：SEO 虚拟数据夹具方案

## 结论和边界

本方案只生成一份可审查的 JSON 数据包，不连接数据库，不启动 API，不调用搜索、抓取、AI 或发布服务。演示对象属于独立逻辑租户 `g-snipers-global-demo`；`tenant_id=4` 在代码中永久拒绝，不能将数据写入老虎。

所有企业、站点、平台页面、竞品和指标均为虚构并使用 `.example` 保留域名。站点状态固定为 `paused`，站点设置同时标记 `scheduler_excluded=true` 和 `external_actions_disabled=true`；分发连接全部 `enabled=false`、无凭证，已有运行记录均为终态。这样，现有按 active 站点筛选的排名、竞品、外链、图片核验及指标调度都不会选中该站点。

生成命令：

```powershell
python -m scripts.build_seo_demo_fixture --output artifacts/seo-demo-fixture-v1.json
```

`--proposed-tenant-id` 只写入供数据库评审的元数据，不会连接数据库；传入 `4` 会立即失败。固定锚点为 `2026-09-01T08:00:00Z`，同样参数重复运行得到相同内容，并以临时文件原子替换输出。

## 对象数量与场景

| 对象 | 数量 | 演示内容 |
|---|---:|---|
| 租户 / SEO 模块 / 站点 | 1 / 1 / 1 | 独立虚拟租户、active 读取权限、paused 站点 |
| 站点级搜索指标 | 361 | 90 天 × 展现、点击、CTR、平均排名，另含 1 条站点收录量估算；全部标记 `source=demo_fixture`、`data_quality=estimated` |
| 关键词 / 排名快照 / 竞品 SERP | 12 / 156 / 36 | 每词 13 个周度点，包含持续提升、持续下跌和基本稳定；3 个竞品的最新排名矩阵 |
| 页面 / 索引意图 / 抓取运行 / 页面快照 | 10 / 3 / 4 / 24 | 健康、待修、已验证、404、noindex、超时；索引意图明确不等于真实收录；运行均已完成 |
| 内容 / 审核事件 | 8 / 9 | 草稿、写作中、待审、已审核待发布、已发布、归档；发布失败由发布记录表达 |
| 分发连接 / 发布记录 / 尝试 | 2 / 5 / 5 | 多平台成功、失败、需要人工处理；连接禁用且无凭证，尝试明确 `provider_called=false` |
| 图片审核 / 重新抓取核验 | 2 / 2 | 一条重新抓取确认修复，一条延后待核实 |
| 内链 / 外链 | 12 / 6 | 包含可追踪 404 内链、有效/丢失/忽略/待核验外链 |
| 竞品 / 动态 | 3 / 3 | 虚拟竞品内容动态；站点 paused 阻止调度，竞品保持 active 以便只读排名接口展示 |
| SEO 任务 / 自动化运行 | 6 / 3 | 排名下跌、待发布、断链、图片修复及完成证据；运行均已完成 |

发布成功、页面检查通过和搜索表现提升是三组独立记录。站点级搜索指标的 `raw_payload.scope=site_daily_total`，且 `article_attribution=unsupported`，数据包中不存在单篇点击字段或内容到搜索点击的映射。

## ID 与幂等导入策略

数据包不硬编码数据库主键，每行使用全局唯一 `_key`，外键使用 `{table, key}` 引用。数据库负责人审核后的加载器应按以下顺序执行单一事务：

1. 通过租户夹具标记查找或创建专用租户，必须确认实际 ID 不为 4。
2. 按表的稳定业务键 upsert，并将 `_key → 实际 id` 保存在本次事务的映射表中。
3. 解析引用后写入子表；只更新具有相同 `fixture_marker=seo-demo-v1` 的行，遇到同自然键的非夹具数据立即回滚。
4. 每次运行强制恢复站点 paused、连接 disabled/无凭证、运行终态，再比较本文件列出的计数。重复执行更新同一组逻辑对象，不追加第二组。
5. 事务末尾运行安全查询；任何 active 站点、enabled/有凭证连接、可运行任务状态、非 `.example` URL 或 tenant 4 命中都回滚。

当前交付没有数据库写入器。这是刻意的审批边界：租户的正式 ID、租户创建归属、JSON 夹具标记落在哪个正式字段，以及跨表清理事务需要数据库负责人确认后才能实现 apply/cleanup 子命令。

## 现有只读接口可见性

| 数据 | 现有只读入口 | 可见性与限制 |
|---|---|---|
| 站点 | `GET /api/v1/seo/workbench/sites` | 可返回 paused 站点，但选择策略会将其列为禁用；工作台如需演示选择，需显式允许只读 demo 站点，不能把它改成 active |
| 搜索指标 | `GET /api/v1/seo/overview/metric-snapshots/latest` | 只能看到各 source/dimension 的最新值，不能返回完整 90 天序列；`GET /traffic/gsc` 只返回连接状态 |
| 关键词和排名 | `GET /api/v1/seo/keywords` | 每词返回所选引擎最新两次排名；13 点历史已存，但没有通用全历史只读接口 |
| 页面和检查 | `GET /api/v1/seo/site-pages`、`/site-pages/issues`、`/site-pages/{id}/detail` | 列表、问题、最近两次快照及依据可见；`indexable` 仅代表抓取到的索引控制状态，不等于搜索引擎已收录 |
| 断链、内外链 | `GET /site-pages/broken-link-report`、`/internal-links`、`/backlinks` | 均读取已存证据，不会触发检查；404 来源关系可追踪 |
| 内容与审核 | `GET /content-assets`、`GET /content-assets/{id}/review-history` | 状态和审核历史分开；`ready` 表示已审核待发布 |
| 发布与尝试 | `GET /content-distribution/publications`、`GET /publications/{id}/attempts` | 发布状态、地址、失败原因和尝试可见；连接只读接口会明确无凭证/未核验 |
| 发布页面依据 | `GET /workbench/publication-page-evidence` | 只对明确 URL 关联返回页面检查；缺 URL、无匹配、多候选和抓取失败继续分别表达 |
| 图片修复 | `GET /site-pages/image-remediation-workbench`、`GET /image-verifications` | 完成只按重新抓取核验 `verified` 计数，approved 本身不算完成 |
| 竞品 | `GET /competitors`、`GET /competitors/rankings` | 可见虚拟竞品和动态；本夹具不发起采集 |
| 待办与指标契约 | `GET /tasks`、`GET /metrics/snapshot` | 任务完成证据与指标分开；paused 站点不会被历史指标采集调度更新，因此 7 日 trend 可能为 null |

## 回滚、清理与测试

清理器应只接受租户 ID和夹具版本双重条件，并按外键反向顺序在单一事务内删除所有 `seo-demo-v1` 对象，最后才删除专用站点、模块和租户。若租户中存在任意不带夹具标记的业务对象，清理必须拒绝，而不是级联删除。清理前后都要输出逐表计数并支持 dry-run。

自动测试覆盖：固定锚点下结果确定；90 天站点指标完整；提升与下跌排名同时存在；内容和发布状态完整；tenant 4 被拒绝；站点、连接和运行状态不可执行；凭证为空；所有 URL 使用 `.example`；搜索指标不能归因到文章；篡改任一安全条件时验证器失败。

## 仍需数据库负责人确认

1. 专用演示租户的正式 `tenant_id` 及创建责任方；必须与老虎 tenant 4 分离。
2. 是否允许在 `tenants` 增加正式 fixture 标记字段，或批准将租户级标记放入既有可审计字段；不能只靠名称判断。
3. `_key` 的长期持久化位置。现有多数表没有 fixture key 字段；若只依赖自然键，版本升级和精确清理的安全性不足。
4. 90 天搜索序列是否需要新增只读历史接口；当前 API 只能返回 latest，不能支持趋势图全部点位。
5. 工作台如何只读选择 paused 演示站点。生产调度要求它保持 paused，不能为了下拉框可选而激活。
6. apply/cleanup 事务的执行身份、允许环境、审计记录和上线审批流程。确认之前不提供生产执行开关。

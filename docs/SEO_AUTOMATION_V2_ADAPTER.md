# SEO automation v2 本地交付说明

本轮仅本地开发与隔离 PostgreSQL 测试；未推送、部署、执行生产 DDL 或调用真实供应商。
共享核心独立提交 `9c538b32f07fb90e8ce131d39b6908fbf39678c8`，另需日志主体修正 `efd6f93b`；
共享回归 76 项通过。适配提交由 Git 历史和测试样例的
`backend_commit` 标识。不修改 SEM / GEO 实现、客户配置或原有审核验收规则。

## 已接操作与实际结果

| operation | 配置对象与边界 | 实际结果 |
| --- | --- | --- |
| onsite_ai | 本站可起草站内任务；版本及事实哈希绑定；复用持久化 AI 队列 | 待审核方案与调用回执；不修改官网 |
| ranking_collect | 本站活跃关键词；明确百度/360/搜狗及 PC/移动 variant；仅绑定站点域名 | SeoRankSnapshot / SERP 事实记录；不启用额外 AI 归因 |
| indexation_collection | 本站域名；复用站长之家查询与缓存 | SeoMetricSnapshot 收录量估算；缓存保留原查询时间，不是单页收录证明 |
| content_draft | 本站已授权 AI 内容计划；绑定实际资料与关键词 | 复用内容工作流生成草稿；质量失败交人工，不自动二次付费修稿 |
| site_diagnosis | 明确登记的本站页面 | 复用抓取及 save_page_snapshot；保留错误、真实快照；新检查发生后不覆盖为迟到结果 |
| incremental_diagnosis | 已启用增量诊断的网站计划 | 复用 robots、sitemap、发现、逐页快照与额度；单轮最多 20 页并受外呼上限约束 |
| monthly_onsite_plan | 本站当月最多 3 个重点词及对应已登记页面 | 创建站内月度任务草稿；不会自动串接 AI 生成，后续可显式选入 onsite_ai |
| monthly_report | 本站已有且尚未冻结的月报任务 | 复用实际发布记录及月度分析生成报告，等待顾问解读；不自动创建整月验收任务 |

以上操作仅在显式配置后接管；未配置站点沿用原开关。被接管操作的旧自动调度及在途结果均检查
归属，暂停/结束不释放给旧调度器。租户排名批次按关键词实际站点拆分，接管 A 不阻止未接管 B。

不在本轮控制范围：竞争对手、外链、独立监测/流量同步、问答批次、图片修复核验、独立手动整站抓取、
平台发布、官网修改、审核、客户确认与验收。单篇文章点击没有新增数据能力。
页面检查完成、草稿生成、发布成功、搜索提升继续分别判断。通用执行成功不产生虚构 completion_evidence。

## 周期与恢复限制

单次执行支持暂停、接管、结束本轮及 end_project。全部步骤结束后仍等待人工处理，项目不会自动转 idle；
启用周期时，须人工 end 本轮后才进入下一次到期检查。来源变化、旧目标已生成方案或月报冻结时应重新配置。
这不是无人值守连续生产，也不承诺自动把上一轮结果转成下一轮输入。

每次真实外呼前提交准入回执；相同 call_key 不付费重试。结果写入前重新检查状态、generation、身份、
归属、服务计划及源对象。停止后的回执可收尾，但不采用迟到业务结果。进程中断且最近准入超过 180 秒时
标记 unknown 交人工，不重新执行。费用只有真实账本证据才 recorded，无证据为 unknown_charge。
单纯 HTTP 抓取记 kind=http / not_called，不冒充供应商费用已对账。

## HTTP 接入

前缀 `/api/v1/seo/workbench/automation-projects`：

- GET `?tenant_id=4&limit=20`：所属项目；next_before_scope_id 游标。
- GET `/2/control?tenant_id=4`：配置、状态、允许动作、controlled / not_controlled。
- GET `/2/configuration-basis?tenant_id=4&operation=ranking_collect&limit=25`：服务端来源版本及候选对象。
  limit 为对象数量，关键词每个对象展开六种 variant；next_before_object_id 指向最后返回对象，不是条目总数。
- PUT `/2/control`：按共享 v2 契约保存；source_bindings 首期必须为空，不接受客户端任意 URL/模型/凭证。
- POST `/2/control`：动作、expected_version、request_id UUID；冲突不隐式重试。
- GET `/2/runs?tenant_id=4`、`/2/runs/{run_id}?tenant_id=4`：运行及实际步骤、来源、回执和证据。
- GET `/2/events?tenant_id=4`、`/2/runs/{run_id}/events?tenant_id=4`：安全事件分页。
- GET `/2/events/export?tenant_id=4&format=json&limit=100`：JSON / CSV；固定 through_id 导出上限。
  CSV 返回 X-Snapshot-Upper-Id / X-Next-After-Id 并防公式注入；无全文/凭证导出。
- GET `/api/v1/seo/workbench/automation-health`：实名全局管理身份，实时重读权限，必须同时具备
  settings.accounts 和 settings.customers edit；拒绝普通顾问、租户身份、API Key 及失效账号。

tenant_id=4 / scope_id=2 仅为测试库合成对象，不是生产联调授权。普通接口要求实名、有效模块、当前站点顾问
分配、站点/内容编辑与关键词查看权限；排名另需关键词编辑。读取不会启动采集/生成任务。响应 no-store。
时间采用显式时区 ISO 时间；计数和分页游标遵循共享契约，不能把当前页长度当总数。
缺结构 schema_pending，越权 403 / 不属于范围 404，参数 422，版本与来源冲突 409，数据库故障脱敏 503。
健康接口故障时保留包络但计数 null；queue=not_connected、worker/overall=unverified，不声称已验证生产进程健康。

## 测试与接入依赖

原生 PostgreSQL + 真实 JWT + ASGI HTTP 测试，供应商全部模拟；无浏览器登录态、真实账号或付费外呼。
22 个相关测试文件综合回归 669 项通过；随后新增进程中断恢复专项，最终专项报告以实际 XML 为准。
SQLite 旧工作流测试仅在其 fixture 模拟“未安装项目 registry”，原生 PG 测试不绕过归属或鉴权。

TEMP 证据（最终提交后重跑生成，不纳入代码库）：

- `seo-automation-v2-comprehensive.xml`：综合回归。
- `seo-automation-v2-http-final.xml`：最终版本专项回归。
- `seo-automation-v2-http-samples.json`：真实测试 HTTP 返回，含 backend_commit / source_tree_clean；
  responses 是 GET 样例，scenarios 保留动作、错误和鉴权分支。只有清洁工作树对应的精确 SHA 样例可作最终基准。

部署前仍需独立批准、数据库负责人审核两个 SQL 候选包及结构对账、旧连接池排空/重建，以及统一前后端版本
集成。程序不自动 DDL、不迁移失败后自动重试写操作。本轮样例及测试证明本地可联调，不代替真实平台发布或生产验收。

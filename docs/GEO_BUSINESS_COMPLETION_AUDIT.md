# GEO 业务完成度审计

审计范围：站内整改、内容审核与分发、可见度与引用、复检验收，以及月度站内任务。
结论中的“自动”只表示代码具备无人值守执行路径；仍需满足租户开通、配置、凭证、审核和调度条件。

| 业务环节 | 当前结论 | 系统实际完成的工作 | 人工或外部依赖 | 代码与测试证据 |
|---|---|---|---|---|
| 官网结构化内容 | 半自动 | AI 只为 `structured_content` 清单项生成有事实引用的建议；服务端校验清单 ID、事实范围和缺失资料 | 人工审核并在真实网站实施；系统不会写客户网站 | `app/geo/onsite_ai.py` 的 `DRAFT_ITEM_KINDS`、`validate_provider_result`；`tests/test_geo_onsite_ai.py`；`tests/test_geo_onsite_postgres.py` |
| 知识库与 FAQ | 半自动 | 与结构化内容相同，可生成并保存版本化建议 | 人工审核、实施和最终质量确认 | `app/geo/onsite_ai.py`；`app/onsite_workflow.py`；`tests/test_geo_onsite_postgres.py` |
| Schema | 规则自动生成，人工实施 | 只从同版本、同 URL、已通过事实校验的可见内容生成 WebPage JSON-LD；不接受模型直接提交 Schema | 人工把结果部署到客户网站 | `app/geo/onsite_ai.py` 的 Schema 分支；`tests/test_geo_onsite_ai.py` |
| llms.txt | 规则自动生成，人工实施 | 从当前版本的公开内容与目标 URL 生成；不接受模型任意 URL | 人工部署文件 | `app/geo/onsite_ai.py` 的 llms 分支；`tests/test_geo_onsite_ai.py` |
| 方案审核 | 人工门禁 | 状态机保存版本、操作者、备注和时间；母稿变化会使旧审核失效 | 客户或具备权限的真实账号提交决定；API Key 不能代替审核身份 | `app/geo/content/review.py`；`tests/test_geo_customer_review_access.py`；`tests/test_geo_customer_review.py` |
| 内容分发 | 条件自动 | 已审核任务在渠道启用、`auto_publish`、有效账号凭证和可用渠道稿同时满足时，可调用真实渠道连接器并记录结果 | 渠道授权、账号凭证和审核；不满足时仅复制/手工发布或阻断 | `app/geo/content/multi_push.py`；`tests/test_geo_publish_delivery.py` |
| AI 可见度与引用采样 | 条件自动 | 巡检按问题与引擎执行真实探测，持久化回答快照、品牌提及和引用；超时任务可被后台收口 | 供应商凭证、巡检配置与调度必须有效；模拟、人工或未知来源不能冒充正式样本 | `app/geo/content/patrol.py`；`app/geo/content/probe.py`；`tests/test_geo_visibility_patrol.py` |
| 正式周指标 | 自动只读汇总 | 正式指标接口按完整自然周与准入规则汇总；回答详情和正式统计分离 | 历史不足时趋势为 `null`；指标不等于客户咨询或成交 | `app/geo/integration.py`；相关 integration/metrics 测试 |
| 站内实施记录 | 人工 | 状态机要求实施备注并保留历史；AI 方案本身不能把任务标成已实施 | 网站维护人员完成真实改站并声明实施 | `app/onsite_workflow.py` 的 `implement`；`tests/test_geo_onsite_postgres.py` |
| 站内重新检查 | 自动检查，人工最终验收 | 系统重新抓取限定域名的真实页面，核对正文、Schema 和 llms.txt；仅新鲜且通过的结果可进入验收阶段 | 网站必须可访问；最终事实和质量由人工确认 | `app/onsite_workflow.py` 的 `recheck`；`app/geo/audit.py`；`tests/test_geo_onsite_postgres.py` |
| 月度站内任务创建 | 已有契约，尚未自动调度 | API 支持 `work_type=monthly` 和严格 `YYYY-MM`，同项目同月份幂等 | 当前必须由工作台或人工调用创建；未发现月度自动创建站内任务的调度器 | `app/onsite_workflow.py`；`app/geo/onsite_routes.py`；`tests/test_geo_onsite_postgres.py` |
| 站内 AI 方案执行 | 条件自动、持久化 | 请求先持久化入队，worker 单次调用供应商，支持轮询、取消、迟到结果隔离、未知计费结果不重试 | 需要有效凭证、调用门禁、计量结构和运行中的 worker | `app/geo/onsite_jobs.py`；`app/geo/onsite_routes.py`；`tests/test_geo_onsite_postgres.py`；`tests/test_geo_onsite_worker.py` |

## 关键边界

1. GEO 能自动生成、校验和复检站内整改方案，但没有客户网站写权限，不会自动改站。
2. 内容自动发布是条件能力，不代表任意租户已经具备真实渠道账号或授权。
3. 可见度、提及和引用是回答观测数据；它们不能直接解释为咨询、线索或成交。
4. 月度站内任务已经能被统一工作台创建和跟踪，但周期性自动建单仍是预留能力。
5. 站内 AI worker 健康只证明当前进程真实执行过 tick；读取接口时间不能充当 worker 证据。

## 后续优先级

1. 驾驶舱先接入只读健康与队列状态，明确区分 `unverified/not_connected/schema_pending`，再开放 AI 方案按钮。
2. 若业务要无人值守月度维护，新增幂等月度建单调度器，并保留租户开通、项目状态和负责人校验。
3. 若业务要自动改站，需要单独建设受限发布连接器、预览、回滚和客户授权；不应复用 AI 方案接口直接写站。

# SEO AI 可见度只读调研

时间：2026-10-19。SEO 基线 `829864d6dd9a96bf832715b67cecf62d9ef69fa4`；GEO 基线 `67706fdaaf7118514aac49a4a7fb1ae985fc8e80`。

## 结论（大白话）

SEO 已有地方存检测结果，不必为第一版新建表。GEO 的检测代码也能放进同一个 SEO 服务里复用，不必新增跨服务调用。

本次按 **B，环境配置契约待确认** 处理，不合并。原因在引擎配置：最新 GEO 的真实豆包、DeepSeek 等采样只读平台托管凭据；SEO 当前 Settings 尚不支持 GEO 各引擎的环境字段。直接拷贝检测模块，会让部分引擎读不到配置或回退模拟，不能当作真实多引擎检测交付。补齐这些字段会扩展 SEO 的环境配置接口，本任务把新增 env 列为停止边界。

这里必须区分：这些名字在 GEO 分支中已经存在，不是全平台新发明的变量；**没有证据证明生产必须新增变量值或新密钥**，因为本次没有读取任何环境文件、变量值或数据库。代码显示服务引用同一环境文件，但不能据此断言其中配齐了所有引擎。用户如果认可“SEO 接受 GEO 既有变量名不算新增 env”，可以转 A，不需要先做数据库迁移。若只允许复用数据库托管配置而不扩展 SEO Settings，则要补专用配置适配器并验证不存在环境回退差异，不能直接导入模块就宣称复用完成。

本次草稿只实现不联网的权限/配额状态转换，并复用 GEO 中立问题生成。没有 API、页面、调度注册，也没有可触发的付费调用。它是可审阅的前置工作，**不是已上线功能**。

## GEO 调研

| 项目 | 源码结论 |
| --- | --- |
| 页面对应检测入口 | `app/geo/content/routes.py` 的 `/answer-snapshots/probe`、`/answer-snapshots/probe-batch`；批量巡检走 `/visibility-patrol/runs`，核心执行在 `app/geo/content/patrol.py`。另一个 `search_visibility.py` 是搜索收录/排名，不能混同 AI 回答提及。 |
| 引擎清单 | `geo_tracking_engines`：租户、engine_key、enabled、sort_order。最新默认含 DeepSeek、豆包、通义、混元、文心、Kimi 等。 |
| 真采样配置 | `app/geo/content/engine_providers.py` 的 `resolve_platform_engine_credentials`；`GEO_<PROVIDER>_API_KEY`、`GEO_<PROVIDER>_BASE_URL`、`GEO_<PROVIDER>_MODEL`。DeepSeek 可回退已有 `DASHSCOPE_*`。这里只读过源码字段名/缺省值，没有读取运行时值。 |
| 托管配置覆盖 | `app/api_connection_config.py` 的 `managed_runtime('geo')`、`load_settings('geo')` 从 `api_control_settings`、`api_control_credentials` 取平台配置；凭据留在运行进程内。`runtime_scope` 已有上下文时直接沿用，故 SEO 上下文内简单套 GEO 装饰器不能保证切换到 GEO 配置。 |
| 历史租户凭据 | `geo_ai_settings`、`geo_tracking_engines` 模型仍有加密凭据字段，但 GEO 最新 `resolve_engine_llm` 明确忽略 engine_row 的凭据；不能为了绕开环境配置直接恢复旧的租户密钥优先级。 |
| 单次采样口径 | `probe.py` 先中立回答，再独立判读；`sampling_method=unprimed_json_v2`。真 API 与模拟样本标记不同，引用准确性不能仅凭回答核实，保留 unknown；判读失败保留原文并标待复核。 |
| 结果 | `geo_answer_snapshots` 存原文、提及、引用 URL、引擎、sample_mode、simulated、patrol_run_id 等；`geo_visibility_patrol_runs` 存逐格 items/summary/status；其 prompt_id 外键指 GEO 问题，不宜把 SEO 关键词直接塞入该表。`geo_prompts` 与优化单元关联。 |
| 调度 | `app/geo/content/geo_scheduler.py` 每小时 minute=5 检查启用的租户；`geo_visibility_patrol_settings` 控制时窗、间隔、词数、引擎，缺省关闭、间隔24小时、词数20。每次默认最多200格、每天默认最多24轮（系统上限不是顾问手动10次）。 |
| 顾问配额 | `advisor_operations.reserve_quota`、`advisor_visibility.check_visibility_quota`、`advisor_quota.py`；按顾问/客户/北京时间日，最多10次。预占后有结果即持久 consumed；无结果只将同一 reserved 条件更新为 refunded；重复清理不能重复扣减。队列任务保留预占关联。 |
| #764 核对 | 公共 GitHub REST 只读确认 #764 已合并：head `588a0726d284ed39a7fd6b583f65b4d5af4e3a4f`，merge `bfeb9d218ea4430af73e8a7d88ea59ded85d9eb0`，2026-10-19 03:34:54 UTC。`advisor_operation_call.checked_call` 在 finally 退未用预占，调用期间/提交前复核撤权，不能只复制“10”的常量。 |
| 调用费用 | `app/ai/deepseek.py` 使用 `metered_request`；费用独立事务记 `api_usage_events`（租户、用户、module、模型、tokens、金额/unknown、pricing_version等），预算准入及托管配置沿用 `api_controls`。实际单价来自平台配置，不是仓库固定数字。顾问退次数不等于供应商退费用。 |

## SEO 调研

| 项目 | 可复用位置与限制 |
| --- | --- |
| 网站 | `app/models/module_workspace.py` 的 `seo_sites`，含 tenant_id、site_settings JSONB；必须核实站点所有权、当前 SEO 开通和 active 状态。 |
| 品牌/关键词 | `seo_brand_assets` 按 tenant_id/site_id 放品牌归属规则；`seo_keyword_assets` 放关键词。`/rank-serp/brand-profile` 使用既有站点设置。使用品牌/别名识别提及，采样问题不能包含待测品牌。 |
| 现有结果表 | `seo_ai_operations.result` JSONB 可保存一次检测结果，已有 tenant_id/site_id/actor/request_key/request_hash/status/expiry。不能直接复用通用退款函数：会动既有 ai_requests 计数；已有回收器30天清理结果、超时退款，部分结果持久化时必须适配其状态，防止误退。 |
| 可用 JSONB | `tenant_modules.module_settings` 可放顾问每日预占元数据；`seo_sites.site_settings` 可放站点检测设置。写入要保留无关键、行锁串行化；不用新增表/列。结果历史可先用既有 operation 行，明确30天保存。 |
| 顾问权限 | `advisor_tenant_auth` 绑定当前所选客户与 grant；`seo_advisor_reads` 按实际站点分配过滤；`advisor_write_routes` 精确路由白名单；`advisor_write_commit` 提交前重查账号、角色、grant 和站点分配；`seo_advisor_audit` 操作记录。不能只前端隐藏按钮。 |
| 既有配额 | `seo_advisor_quota.py` 是现有“AI建议”10次配额，不含失败无结果退款语义；AI可见度应独立计数，沿 GEO reserved→consumed/refunded 原理，不能误挤占其他建议额度。 |
| SEO 配置差异 | `app/config.py` 已有 DASHSCOPE_*、DEEPSEEK_*，没有 GEO_DOUBAO_*、GEO_DEEPSEEK_* 等。`api_connection_config.CATALOG` 虽已列 GEO 连接，load_settings 对不存在的属性会跳过，单纯读取同一数据库不能自动补齐。 |
| 费用与隔离 | provider 请求仍归 `module=seo`，不能因读 GEO 配置把账记到 GEO。需在集成时确认固定 provider binding/预算，控制服务不可用时拒绝付费调用。 |

## 数据库与服务边界

`deploy/seo-service.service` 和 `deploy/geo-service.service` 都引用 `/opt/sem-backend/.env`，分别启动独立 SEO/GEO 应用；`deploy/README-GEO-INDEPENDENT.md` 写明数据库配置与认证表共享。由仓库设计可判断二者共用平台数据库；**没有连接数据库或查看服务器，不能把代码设计当作现场实例/ACL/当前revision的验收证据**。

没有找到可直接复用、具有服务间身份及所选租户授权的 SEO→GEO 内部调用协议。现有 GEO 业务 API 走用户/API鉴权，不以“同机/内网”自动信任 SEO。新建 HTTP 通道会引入地址/凭据/授权传递，本方案不采用。

## 本次草稿与验证边界

`app/seo_visibility_policy.py` 无数据库/网络/邮件/环境访问；`VisibilityScope` 必须由未来适配器从服务端实时权限构造，不能作为客户端输入。`reserve_quota/settle_quota` 是纯转换，尚未持久化，不声称通过并发集成或运行时撤权验收。调用方必须持有 tenant_module 行锁、用 durable operation 防跨日重放、第一条结果与 consumed 同事务提交，然后才调用下一引擎；无结果清理只改该预占。

模拟测试覆盖所选客户、授权/分配、跨租户、读写权限、配置仅超管、10次上限、分顾问/客户/北京时间日、全失败退款、部分结果不退、重复退一次、旧日/他人预占不能影响当天、幂等重放与GEO中立问题复用。网络连接在测试中被显式禁止。无接口挂载，因此真实 HTTP 权限、数据库锁/并发、后台撤权、供应商计费与前端联调均待集成后验证，不能以纯单元测试替代。

方案见同目录 `plan-aivis.md`；仓库内对应 `docs/SEO_AI_VISIBILITY_PLAN.md`。

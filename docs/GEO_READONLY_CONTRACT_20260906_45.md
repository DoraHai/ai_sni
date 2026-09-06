# GEO 工作台首期只读契约与修改方案

日期：2026-09-06。状态：供评审的拟定契约，新增接口尚未实现。本文不授权采集、生成、发布、部署或数据库变更。

后续记录：用户已授权按“Brief/版本 → 跨语言证据 → 工作台接口”的顺序开发，现已完成本地接口实现与离线测试。本文保留原设计；实际实现范围、配置模式的进一步澄清和待验收项见 `GEO_BRIEF_EVIDENCE_READ_IMPLEMENTATION_20260906.md`。尚未部署。

核对基准：GEO `codex/production-geo`，代码 `d10090734e182e0a8a9e19fbbbc4db0b857ef16a`；原型 `20260906-45`，来自 `cockpit-foundation/cockpit/prototype/cockpit-prototype.html` 及其引用的 `geo-depth.js`、`tracking-boundary.js`、`task-handoff.js`。`geo-depth.js` SHA256 为 `5f18c07581ac8c31ca0f07b4ccc86177f6fce9162c7ea9e1cca55ec881d0e091`，与该版原型留档 manifest 一致。

本文细化并取代 `GEO_WORKBENCH_API_REVIEW_20260906.md` 中的首期接入范围和工时估算；共享 Task 最小字段、Metric 五字段及 trend_7d 格式均不改。

## 1. 首期接口白名单及副作用

以下路径统一加 `/api/v1/geo`，必须携带 `tenant_id` 并通过现有租户鉴权。这里的只读指业务数据无插入、更新、删除，不发起模型调用、网站抓取、配置初始化、任务调度或状态修复；普通访问日志不属于业务写入。

### 可复用的现有 GET

|接口|结论与首期用途|
|---|---|
|`/integration/metrics/snapshot`|可直接用。正式数值唯一来源；支持 `week_end=YYYY-MM-DD`，只允许已结束的周一边界。返回五字段指标列表。|
|`/integration/metrics/dictionary`|可直接用。同租户、同 week_end 取字典，包括动态竞品 key 与一句话口径。|
|`/prompts`|可查询现有问题清单；问题文本是当前文本，不能冒充回答发生时的历史提问。|
|`/answer-snapshots`|业务处理只读，但缺历史模型、时间范围、分页及正式采纳解释；可作旧页面来源，不是新聚合契约的直接替代。|
|`/content-tasks`|列表路径只读，已有 limit/offset；可显示摘要。不要随后调用有初始化副作用的旧详情。|
|`/integration/tasks`、`/integration/tasks/{id}`|可直接读取统一指标任务及完成证据。ID 属于 GeoActionTicket。|
|`/integration/tasks/{id}/retest-plan`|可只读取得复测计划；不满足条件可能返回 409，不会启动巡检。|
|`/integration/tasks/{id}/baseline-readiness`、`/execution-readiness`|可读取条件/阻碍；后者的 `tenant_auto_push_matrix` 与 `prepare_retest` 为配置查询和校验，不初始化渠道、不触发推送。|
|`/visibility-patrol/settings`、`/visibility-patrol/ops-status`|业务处理只读。ops-status 中 ready_for_real 仅为配置推断，不能当真实连接成功或实际采集模式证明；不拿其中当前模型填历史回答。|

以上是代码链路核对结论，不代表已执行生产接口或完成数据库只读权限验收。首期实施需以禁止 DML 的测试验证白名单。

### 不可用于严格只读工作台的旧 GET

|接口|已确认的副作用|处理方案|
|---|---|---|
|`/tracking-engines`|调用 `_ensure_default_engines`，可能初始化/调整配置|新配置视图只 select；无配置明确返回 `unconfigured`，不落库默认值。|
|`/content-tasks/{id}`|详情 `_task_payload(detail=True)` 的 channel_options 调用 `_ensure_default_publishing_channels`|新详情适配器只取已有对象与渠道，缺渠道返回空列表。|
|`/visibility-patrol/runs`、`/visibility-patrol/runs/{id}`|`reconcile_stale_patrol_run` 可能回写超时失败|新查询返回持久化状态及独立 stale 提示，不修复状态。|
|`/async-jobs`、`/async-jobs/{id}`|reconcile 可能改异步任务和内容任务状态|同上；读取进度不触发恢复。|

未列出的旧 GET 不自动进入白名单。评分、检查就绪、AI 审校、生成、复测、发布核验等 POST 均不在首期调用范围。

### 拟新增的纯查询端点

以下路径**均为提案，不是现有可调用接口**，统一位于 `/api/v1/geo/integration/read`：

|GET 路径|用途|
|---|---|
|`/answers`、`/answers/{snapshot_id}`|分页回答、原文、历史来源、样本资格和指定正式周的采纳说明。列表返回摘要；详情返回完整原文，适用同一资格字段。|
|`/period-context`|返回正式完整周与前周边界、门槛、覆盖数量、指标缺数原因、比较条件和 canonical 指标/字典地址。不给另一套汇总分数。|
|`/capabilities`|已有引擎/渠道的脱敏配置摘要；明确 `configured`、`effective_mode`、缺项、未做连接验证。不初始化或试连。|
|`/content-tasks/{content_task_id}`|内容详情、版本来源、渠道稿/发布记录、已知关联，绕开渠道初始化。|
|`/patrol-runs`、`/patrol-runs/{patrol_run_id}`|现有巡检列表/进度、逐单元失败原因、已有快照引用。|
|`/async-jobs`、`/async-jobs/{async_job_id}`|现有异步任务列表/进度、错误和产物引用。|

不新增通用任务表，不改变现有路由行为。新端点内部直接调用无副作用的查询服务，不能通过 HTTP 转调有副作用的旧 GET。禁止 ORM autoflush，使用独立查询 session；测试拦截 DML、flush/commit、网络和后台调度。支持时使用数据库事务级 READ ONLY，不能依靠最终 rollback 掩盖已经发生的外部动作。当前阶段只写方案，不创建数据库角色或修改数据库。

超时示例：`{"stored_status":"running","stale":true,"stale_reason":"elapsed_threshold_exceeded","progress_pct":45}`。stale 仅表示按已存时间和配置阈值推断“耗时超限，待后台确认”，不证明 worker 已失活；当前恢复还检查执行锁，新查询不能获取该执行锁或运行恢复。不得将其序列化为“已失败”冒充持久化状态；后台恢复机制保持独立。进度未知为 null，不用假百分比；错误仅返回脱敏 code/message，不透传凭证、完整 request_meta 或堆栈。

## 2. 回答契约、时间、来源与正式采纳

完整示例见同目录 `GEO_READONLY_RESPONSE_EXAMPLE_20260906_45.json`，其中所有回答/任务 ID 和正文均为虚构契约样例，不是验收或生产记录。

### 查询及分页

`GET /integration/read/answers?tenant_id=1&week_end=2026-08-31&captured_from=2026-08-24T00:00:00%2B08:00&captured_to=2026-08-31T00:00:00%2B08:00&limit=50`

- 可选过滤：prompt_id、engine_key、source_kind、patrol_run_id；观察时间为 `[captured_from,captured_to)`，必须有时区。UI 日期末日包含在选择范围时，转换为次日零点独占边界。
- `week_end` 是解释采纳状态的正式周，独立于回答观察范围；省略时解析为最近完整周，并在响应明确返回。观察范围可含本周，但不能让正式指标改算未结束周。
- limit 默认 50，上限 200；按 captured_at DESC、id DESC 稳定排序，未知时间放最后。opaque cursor 绑定租户、过滤条件、排序、已解析 week_end、首屏最大 ID 和末条排序键。条件不匹配或篡改返回 400 `invalid_cursor`，不得跨租户复用。
- `next_cursor=null` 代表末页，`has_more` 明确返回。首次查询固定最大 ID，排除翻页期间新增的历史日期记录；已有记录被更正仍可能影响后续页，返回 evaluated_at，不宣称跨请求不可变快照。筛选变化必须重新从首屏开始。
- 无时间范围筛选时允许展示时间未知的历史记录；有时间筛选时无法确认落窗的记录不混入结果，响应附 `unknown_time_count` 供 UI 提示可清除时间筛选查看。该数量为同租户其他过滤条件下时间未知的条数，不是正式合格样本数。
- 来源筛选只作用于回答列表，不能改变 period-context 的全租户正式周样本范围。分页当前页数量不是全周合格数量。

### 字段语义

|字段|来源/定义|
|---|---|
|`ref`|`{module:"geo",type:"answer_snapshot",id:...}`；ID 不是任务 ID。|
|`question`|id 为 prompt_id；historical_text 取关联巡检 item.prompt_question；current_text 单独取当前问题。无历史原文则 null，禁止回填当前文本伪装历史。|
|`engine`|key 来自快照；provider/model 取对应服务端巡检 item，不取现时配置；metadata_source 明确来源。|
|`engine.model` / `model_revision`|前者是历史记录的请求模型名/别名，后者是不可变修订号；当前数据通常没有后者，返回 null。模型别名一致不能证明供应商内部模型未变。|
|`captured_at`、`captured_at_local`|UTC ISO8601 Z 与 Asia/Shanghai 的 +08:00 展示；明确 time_basis。按既有存储契约解释已知 UTC naive 时间，不能当浏览器当地时间。未知/不可确认历史时间返回 null 并带解释，不能虚构精确时刻。|
|`source.kind`|real/manual/simulated/unknown，用于来源展示；保留 stored_sample_mode 与 simulated，不把模式字段当真实性凭证。|
|`source.verified_server_record`|服务端巡检及单元关联验证是否通过，独立于 kind。人工填 openai_compat 并不会变成可信真实样本。|
|`sample_eligibility`|本条是否通过正式指标的样本规则；不包含周数量不足、窗口外、模型历史不足以同比等周期条件。|
|`week_membership`|是否处于指定正式周，是否进入该周合格 cohort；窗口外单独说明，不把它叫虚假回答。|
|`metric_adoption`|逐 metric_key 返回 included/excluded/unavailable，以及本条或整周原因；included 表示参与该指标统计，不表示该回答提及了品牌。只对本周字典中的实际 key 生成。|
|`comparison_metadata`|历史题目/模型信息是否足以比较；单条信息完备不代表整周可比，最终看 period-context。|
|`relations`|仅返回已经持久化且同租户校验通过的有类型关联，缺失为空，不根据题目相同推定关联。|

### 样本规则与原因分层

复用 `integration_metrics.py` 和 `sample_provenance.py` 的现有判定，抽取同一诊断服务供正式指标与只读解释使用，避免两套规则。

本条准入要求：非品牌点名题、真实 API、`unprimed_json_v2`、判读 completed、引用未标为 inaccurate、同租户有效问题、对应已完成服务端巡检；采样时间在巡检起止内，snapshot_id 对应单元，原文/问题ID/引擎/提及判定/竞品/引用等与巡检记录一致。未标错不等于人工确认每个引用事实正确，界面勿扩大承诺。

拟定稳定原因码（允许多项，配中文 message）：

- 行级：`simulated_sample`、`manual_sample`、`unknown_source`、`unsupported_sampling_method`、`analysis_incomplete`、`citation_inaccurate`、`brand_probe`、`missing_server_evidence`、`patrol_not_completed`、`snapshot_patrol_mismatch`、`capture_outside_patrol`。具体分支在实施时与现有谓词逐项测试对应，不能仅看 source.kind 放行。
- 窗口级：`outside_selected_week`。不进入本周不代表永远不合格。
- 周级：`insufficient_samples`、`insufficient_questions`、`insufficient_engines`；可见度分数另有 `missing_own_domain`。
- 比较级：`previous_week_insufficient`、`current_week_insufficient`、`cohort_changed`、`question_changed`、`model_metadata_missing`、`model_distribution_changed`、`sample_distribution_changed`。

**合格样本即使整周仅 7 条仍是合格样本**：sample_eligibility.eligible=true，week_membership.included_in_cohort=true；周状态 insufficient，metric_adoption=unavailable、scope=week，正式 value=null。模拟样本则 eligible=false、adoption=excluded、scope=sample。这两者不可合并成一个“不采纳”布尔值。

采纳状态优先级：本条不合格或窗口外 → excluded；本条合格且在周内、但对应指标因周门槛/缺自有域不能出数 → unavailable；其余 → included。周门槛仍在 period-context 独立说明，不能覆盖模拟样本的行级排除原因。这里是“是否参与统计”，不是“是否带来正向贡献”。

缺历史 provider/model 会阻止可靠比较，但现有单周准入未以该字段完整性作为单独必要条件；不得在展示层擅自增加排除规则。未知时间等历史异常也不得悄悄改正式指标；应暴露数据质量问题并按既有规则核对，必要时单独提出修复。

### 模拟模式专项结论

现有 TrackingEngineItem 默认 `mock_persona`；种子配置和 UI 也存在模拟默认。`prefer_real=true` 不是 `real_only`，混合路径可能使用模拟或其他租户模型兜底。首期 `/capabilities` 应忠实展示实际配置与可能回退，不替用户更改生产配置。

正式指标必须保留服务端证据验证，不接纳模拟、人工或未知来源；人工把 sample_mode 填成 openai_compat 也不能绕过。真实 API 回答与面向消费者的 AI 网页回答是不同采集环境，界面需要明确。品牌提及、引用均不是客户咨询，不生成咨询量、线索量或转化归因。

## 3. 正式周期与指标解释

- 时区 Asia/Shanghai；自然周周一 00:00 至次周周一 00:00，左闭右开。2026-09-06 默认正式周为 `[2026-08-24T00:00:00+08:00,2026-08-31T00:00:00+08:00)`，as_of 为结束时刻；前周为 08-17 至 08-24。本周 08-31 至 09-07 仅观察，不是完整周基线。
- `/period-context` 返回 timezone、current/previous 的 start/end、closed、canonical week_end、minimum_counts、qualified_counts、metric_status、comparison、metrics_url、dictionary_url、evaluated_at。
- 门槛为至少 8 条合格回答、3 个问题、2 个引擎，均来自全租户该周有效样本，不能让前端按当前页/当前来源过滤器重算。
- 提及次数：提及品牌的合格回答数，每条最多一次。提及率：上述条数/合格回答数×100。可见度分数：50×提及率小数+50×自有域引用率小数；自有域只取启用 website/docs 渠道域名。竞品每回答按归一名称去重，使用现有字典 key。品牌和竞品使用同一周、同一合格 cohort。
- 周门槛不够返回 null；足够且确实无提及才是 0。缺自有域只阻塞分数，不自动抹掉已经可算的提及次数。
- trend_7d 原样保留 `{direction,change_pct,change_abs}`。前后周都足够且问题/引擎 cohort、历史题目原文、provider/model 分布及每格样本次数一致才比较；缺少历史则整个对象 null。前周值 0 时 change_pct=null，但可计算 change_abs 和 direction。不把 up/down 当好坏。
- 指标接口不加第六字段。上下文解释通过独立接口提供；指标数字只消费 canonical snapshot。各请求带同一个显式 week_end；仅新增查询视图返回 evaluated_at，现有五字段指标中的 as_of 仍是周末时刻，不是读取时间。当前未实现冻结版本号，数据更正期间不能宣称跨接口原子一致。出现解释/数值矛盾时整组重取并显示更新中，不能前端补算。

## 4. 任务关系与进度契约

统一 `ObjectRef={module:"geo",type:<下表类型>,id:<原生整数ID>}` 仅用于新查询视图，不改共享 Task 契约。

|type|实体/状态|可用的真实关联|
|---|---|---|
|`metric_task`|GeoActionTicket，共享 open/in_progress/done/cancelled|params.content_task_id；progress.retest_runs 中 window→patrol_run_id；完成证据按共享 Task 原样读取。|
|`content_task`|GeoContentTask，内容/客户审核自己的状态|prompt_id；article_versions；variants；publications。不能把 editing 等强转成指标任务 done。|
|`article_version`|GeoArticleVersion；id 与 version_no 分开|task_id；generation_meta.async_job_id（存在时）；手动保存版本明确 generation_source，不能当 AI 成功生成。|
|`channel_variant` / `publication`|渠道稿 / 发布记录|variant.article_version_id；publication.variant_id；发布成功不等于效果改善。|
|`patrol_run`|GeoVisibilityPatrolRun，pending/running/completed/failed|summary.contract_plan.task_id（指标任务）；items.snapshot_id；completed 时仍可能有失败单元。|
|`async_job`|GeoAsyncJob，pending/running/succeeded/failed/cancelled|ref_type=content_task + ref_id；result_meta 中已有产物引用，经同租户核实后返回。|
|`answer_snapshot`|GeoAnswerSnapshot|patrol_run_id、prompt_id。|

同为数字 14 的不同对象不能互换。普通巡检不是 GeoAsyncJob；题目相同仅是相关数据，不证明“该内容导致该指标变化”。若无显式关联返回空，不建立新关系或回填数据库。前端路由带对象类型；所有联表关系校验 tenant，错租户资源返回不泄露存在性的结果。

后续执行接口仍各用自己的 ID：生成 POST `/content-tasks/{id}/generate?...&run_async=true` 返回 `job.id`；真实巡检 POST `/visibility-patrol/runs` 返回 `run.id`；统一任务 POST `/integration/tasks/{id}/retest` 返回 `run_id`。本期不调用这些接口。

巡检查询返回 stored_status、stale、progress（可确定时）、summary、逐单元 ok/error/skipped_reason/fallback_reason、snapshot refs；异步查询返回 stored_status、stale、progress_pct/progress_label、脱敏 error、产物 refs。失败未产生新版本时返回产物空，不把保留的旧稿当新结果。首期轮询仅查询已有对象，切换客户需取消旧请求/丢弃迟到响应。

## 5. 与原型 20260906-45 的具体对照

|原型位置/行为|正式接入方案|
|---|---|
|问题×AI 平台矩阵，使用字符串和数组索引 GQ-*|使用 prompt_id + engine_key；同格多次回答显示条数和最新时间，并可查历史，不靠数组 `.find` 顺序挑选。|
|平台固定 DeepSeek/豆包/通义千问|用已存在配置及观察历史的 engine_key 联集展示，停用/历史引擎单独标记；配置缺失不自动创建。|
|日期筛选与下钻|保留所选回答观察范围；旁边独立显示正式完整周，不能把任意日期筛选替换正式周期。|
|回答原文、提及、引用、竞品|读聚合详情，明确来源、模型别名/修订号、时间精度、引用 URL；无引用地址返回空，不能拿示例 URL 补齐。|
|空格“暂无回答/待获取回答”|仍显示无样本，不能解释成未提及。样本合格但整周不足显示“样本合格，整周暂不出数”。|
|正式分数 —、模拟回答数量|分数由 canonical snapshot 提供；回答来源分布仅为观察性统计，模拟数量不参与正式分母。|
|“安排获取真实回答”、再次检查、内容改进|首期只展示计划/前置条件或禁用说明，不调用写接口。若保留原型本地计划，要明确未创建服务端任务。|
|task-handoff 的 active/review/waiting/done|保留其原型性质，不映射成 GEO 任务真实状态；客户审核仍是一道，不能额外增加内部审批。|
|tracking-boundary 中提及/引用和咨询的边界|继续保持；咨询数据缺失显示未知，不把曝光或提及当咨询。|

## 6. 实施分期、依赖与工作量

原 5–8.5 人日估算包含聚合、基础工作台适配、纯查询预检和只读回归，但**没有把完整的渠道初始化隔离、所有进度查询适配、独立周期上下文及类型关联逐项算清**。不能说现在明确的全部纯查询范围已完整覆盖。按本次范围重估如下；这是工程人日，不是自然日或已完成工时。

|阶段|工作|估算|
|---|---|---|
|A 首期只读|后端：共享诊断服务、回答分页/详情、周期解释、配置/内容/巡检/异步纯查询适配及对象关联|2.5–3.5 人日|
|A 首期只读|工作台：矩阵/证据/来源/周期、已有任务进度与空态，替换模拟数据调用|1–1.5 人日|
|A 首期只读|契约联调、禁止副作用测试、租户隔离、时间/样本/比较回归|1–1.5 人日|
|A 小计|明确包含上述纯查询改造|**4.5–6.5 人日**|
|B 后续真实采集|严格 real_only 入口/有效配置预检、无模拟回退、失败原因、复测入口接线，复用已有巡检/异步基础设施|1–1.5 人日|
|B 后续真实采集|前端动作接线、受控供应商联调、幂等/错误/恢复回归|1–1.5 人日|
|B 小计|不含等账号/审核/完整周积累的日历时间|**2–3 人日**|
|合计|本次细化后的范围，替代旧的粗估|**6.5–9.5 人日**|

A 依赖：原型契约确认、前端协作与既有鉴权/租户范围；现有数据不足可使用明确标为测试的离线 fixture 联调，不需要真实渠道账号、模型调用或数据库迁移。若数据库性能验证发现必须新索引，另报变更，不包含在当前授权。

B 依赖：明确批准真实采集、有效 AI 供应商配置/额度和授权、固定问题矩阵及可追溯模型信息。真实 AI 回答采集本身不依赖发文渠道账号；发布后效果闭环另外依赖可信内容、客户审核、有效发布账号及真实链接核验。H1 完整出稿验收和 H3 发布授权缺口仍独立存在，不能用纯查询通过替代。

不包含：新增消费者网页自动化采集、供应商不可获得的精确模型修订号、CRM 咨询归因、自动改变生产配置、数据清洗/迁移、生产部署、等待自然周及真实经营效果证明。若这些成为必需项需重新估算。

## 7. 后续实施的验收要求（本轮未执行）

1. 空租户连续查询不会新增引擎/渠道/设置；过期 running 巡检/异步任务读后数据库状态不变。
2. 新端点查询在禁止 DML、禁止外部网络和后台任务的测试约束下通过；兼容旧模块行为。
3. 真实、人工、模拟、未知、伪造 real 标记、巡检内容不一致分别给出正确行级原因。
4. 合格 7 条不出周值；8 条但不足 3 题或 2 引擎仍不出；条件足够且零提及时返回 0；缺自有域只阻塞分数。
5. 上海周一边界及 UTC 换算、当前周观察、历史模型缺失、模型/题目/采样分布变化、前值 0 的 trend 分别验证。
6. 聚合资格与正式 snapshot 的 sample_ids/谓词一致；字典及指标均保持共享格式，正式数字不从回答列表汇总。
7. 分页无跨租户游标，重复时间稳定排序；内容/指标/巡检/异步相同整数 ID 也不会串对象。
8. 前端按 20260906-45 验证：空样本不等于零提及；数据来源和排除层级独立；只读界面不调用采集、生成或发布。

核查入口：`app/geo/routes.py`、`app/geo/content/routes.py`、`app/geo/integration.py`、`app/geo/integration_metrics.py`、`app/geo/retest.py`、`app/geo/content/sample_provenance.py`、`app/geo/content/multi_push.py`、`app/geo/content/engine_providers.py`。

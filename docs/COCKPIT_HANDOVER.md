# 经营驾驶舱 · 交接清单

> 面向对象：接手继续开发驾驶舱的下一个 AI/开发者。
> 状态：**概念设计 + 后端骨架（假数据）+ 交互原型已完成，尚未接入任何真实数据源。**
> 本文档和 `cockpit/` 目录是本次交接的全部产出，其余上下文不存在，请以本文档为准。

## 0. 一句话说清楚这是什么

驾驶舱不是"SEM/SEO/GEO 三个模块仪表盘拼在一起"，核心价值是**跨模块归因**——发现"A模块的变化能不能解释/影响B模块"这种运营团队看不到的关联，用对话的方式讲给决策者听，决策者拍板后可以直接派发任务给对应模块的执行方，并且追踪任务是否真的被执行、效果如何。面向的是"不看操作细节、只做资源分配判断"的决策者角色，不是给专业运营用的操作台。

## 1. 核心设计原则（改动前必须先理解，否则容易做歪）

1. **发现和解释要分开**：跨模块关联的判断必须来自离线的、确定性的、可测试的"信号引擎"（规则由人定义，不是让对话时的大模型临场发明因果关系）；对话里的 AI 只负责把已经确认的信号讲清楚、回答追问、派发任务。这条线不能模糊——模糊了迟早会有一次"把两个无关数字硬凑成因果"讲给决策者听，产品信任就没了。
2. **完成判定必须看真实数据变化，不接受自报完成**：任务契约里的 `completion_evidence` 必须指向一个真实指标的变化，不是"运营点了个完成按钮"。
3. **数据可信度必须诚实标注，不能给假信心**：不同数据源的可信程度差异很大（见第4节 GEO 的例子），驾驶舱如果把"模拟估算的数字"和"真金白银的花费数字"用同样的语气呈现，是在系统性地误导决策者。
4. **驾驶舱是独立服务，不挂靠在任何一个模块的代码库下面**：只通过约定好的接口去"拿数据、派任务"，不直接连 SEM/SEO/GEO 的数据库。这条是从这个仓库这几周 SEM 前后端分支互相搞混的真实教训里得出的——角色边界模糊，迟早会有人真把错的东西部署到错的地方。

## 2. 分阶段路线图（当前进度：阶段1完成，尚未开始阶段2）

- **阶段0**（进行中/待确认）：SEM/SEO/GEO 三个模块各自补齐基础设施——通用任务/工单机制、只读指标快照接口。见第5节三份任务说明。
- **阶段1**（✅ 已完成，见第3节）：驾驶舱后端骨架搭好，用假数据把"拉取→缓存→聚合"这条管道跑通，验证共享契约的接口形状。
- **阶段2**（未开始）：和业务专家一起定义第一批信号规则（3-5条），落地信号引擎，大屏首页的"一句话研判"改由信号驱动。
- **阶段3**（未开始）：接入对话引擎，只读不执行——CEO 能问、AI 能实时查数据回答、能解释信号依据，但不开放任务派发。
- **阶段4**（未开始）：打开"对话确认→创建任务→追踪完成"的完整闭环，建议先在一个客户身上试点。

**不要跳阶段。** 尤其不要在信号规则还没被验证可信之前就开放任务派发能力。

## 3. 当前代码状态

### 3.1 后端骨架：`cockpit/app/`

一个独立的 FastAPI 聚合服务，**所有数据都是手写的假数据**，用来验证共享契约（第4节）的接口形状是否够用。

- `contracts.py` —— Pydantic 定义的共享契约本身（Metric / Task / Signal），这是最重要的文件，任何字段改动都要先改这里
- `sources.py` —— 模块数据源抽象（`ModuleMetricSource` 基类 + 三个 Mock 实现）。**接入真实数据时，只需要把这里的 Mock 类换成真正发 HTTP 请求的实现，上层 `main.py` 不用动**
- `signals.py` —— 信号引擎的占位实现，现在硬编码返回一条信号（对应原型里演示的那个"SEM花费集中+SEO内容承接+GEO提及量突增"场景）。做阶段2时，这里要换成真正读取 `sources.py` 数据、跑规则库的实现，函数签名 `evaluate_signals(tenant_id)` 不用变
- `store.py` —— 任务台账，目前是进程内内存字典，重启即丢。做数据库持久化时只改这个文件
- `main.py` —— 路由层：`GET /api/v1/cockpit/metrics`、`GET /api/v1/cockpit/signals`、`POST /api/v1/cockpit/tasks`、`GET /api/v1/cockpit/tasks`、`PATCH /api/v1/cockpit/tasks/{id}/complete`（要求带 `completion_evidence`）

跑起来的方式：
```bash
cd cockpit && pip install -r requirements.txt
uvicorn app.main:app --port 8899
```
四个接口都已经手工验证过能跑通（`/health`、metrics 聚合、signals、task 创建+完成）。

### 3.2 交互原型：`cockpit/prototype/cockpit-prototype.html`

单文件 HTML/CSS/JS，纯前端演示，**不连接 3.1 的真实后端**（所有数据是页面里手写的，Artifact 沙盒本身也不允许连 localhost）。这是这次交接里唯一经过多轮迭代、相对成熟的部分，建议接手方先完整看一遍这个文件，理解交互结构再动手：

- **四种界面模式**：对话为主（默认）/ 大屏为主（"全域数据"视图，对话缩成窄栏）/ 左右分屏（可拖拽调整比例）/ 全屏看板（对话缩成悬浮气泡）——右上角常驻切换器随时切换
- **大屏内容结构**：关联全景（因果链条+三模块概览+支撑依据+其他关注点+本周动态）+ SEM/SEO/GEO 三个深入视图，每个深入视图内部按"总览指标→效果数据表→任务台账/流程步骤条→可执行任务类别全览"分节展示
- **全面可点击**：数字、表格行、卡片、文字段落全部可点，点开显示更细的下钻说明（通用元素走自动挂载的通用弹窗，少数关键节点如关联全景的三个链条节点有手写的真实下钻内容作示范）
- **趋势图可放大、可配置**：所有 sparkline 点击后打开一个多指标叠加的大图，支持切换时间范围（7/30/90天）、点图例显隐某条线——图表数据是伪随机生成器（`genSeries`），正式版本要换成真实的逐日数据查询

这个原型里出现的具体数字（花费、CTR、品牌提及率等）**全部是编造的示例值**，唯一的例外是**字段名和数据来源说明是基于对三个模块真实代码库的调研**（见第4节），可以直接作为"这个数字该长什么样、该标注什么来源"的参照。

## 4. 三个模块真实能提供什么数据（调研结论，非常重要，接手方不要重新猜）

这是花了好几轮才调研清楚的，**直接复用，不要凭空假设字段**。

### SEM（`app/baidu/*`、`app/models/*`）
- `kw_report_snapshots` 表：展现、点击、花费、CPC、CTR、平均排名、转化数、质量度（`quality_enum`）、落地页体验分、上方位竞价指标（`top_pageviews`/`top_pclicks`/`top_pay`）——逐关键词逐天
- `BidWriteback` / `WritebackAction`：完整写回状态机（`pending`/`success`/`failed`/`reconcile`/`dry_run`），带操作人、旧值新值——这就是真实的任务台账
- `app/ai/expansion_eval.py`：AI 扩量评估自带结论+理由+建议出价（`relevance`/`recommend`/`reason`/`suggested_bid`/`bid_reason`）
- `daily_insights` / `monthly_reports` 表：**SEM 已经有每日/月度 AI 叙述生成能力**（DeepSeek 基于 KPI+环比+告警+百度官方波动归因生成），驾驶舱的"今日要点"不应该重新生成，应该直接引用这个
- `Alert` 表：`rule_code`/`priority`(P0~P5)/`title`/`message`

### SEO（`app/models/seo.py`、`app/seo_*.py`）
- `SeoMetricSnapshot` 表：**这张表的形状几乎就是驾驶舱指标契约本身**（`metric_type`/`numeric_value`/`unit`/`data_quality`/`status`/`observed_at`，连"是不是估算值"都有字段）——如果 SEO 窗口的指标快照接口就是包装这张表，对接成本应该很低
- `SeoAutomationRun`：`planned_count`/`success_count`/`failed_count`/`skipped_count`，真实任务进度
- `SeoContentAsset.status`：完整内容生命周期状态机
- `SeoImageAltReview`：图片修复审核状态，"完成"的判定口径是**重新抓取确认**，不是"审核通过就算数"（这条是和 SEO 窗口专门确认过的）
- `app/seo_traffic.py`：**Google Search Console 真实数据**（曝光/点击/排名，官方口径，不是内部爬虫估算的）
- `app/seo_serp.py`：多引擎（百度/谷歌/必应）SERP 采集
- `app/seo_rank_optimization.py`：**排名下滑→自动生成待审核内容任务，这条链路已经存在**，驾驶舱不需要重新判断"要不要写内容"

### GEO（`app/models/geo_*.py`、`app/geo/*`）—— 一个必须知道的关键坑
- `GeoDailyMetric`：品牌提及率、点名认知率、Top1占比、独立引用域名数、竞品提及对比，按天汇总
- `GeoActionTicket`：整改工单，`status`/`acceptance_type`/`last_verdict`
- `GeoAuditRun`：诊断评分+发现+建议
- **`GeoTrackingEngine.sample_mode` 默认值是 `mock_persona`（模拟人设，不做真实抓取）**，必须客户/管理员主动为某个引擎配置真实的 `openai_compat` 端点+密钥，那个引擎的样本才是真实探测结果。`GeoAnswerSnapshot` 还有一个 `simulated` 布尔字段和 `sample_mode: manual | openai_compat | mock_persona` 三态。
  **驾驶舱展示任何 GEO 可见度数字，必须同时标注这个数字背后的样本构成（真实引擎/人工核实/模拟人设的比例），不能裸给一个数字**——原型里已经做了这个标注，可以直接参照那个 UI 模式。
- `app/geo/pagespeed.py`：网站体验数据现在跑的是**本地 Lighthouse**，不是 Google 官方 PageSpeed/CrUX（文档写着"如未来恢复"，说明曾经接过官方、现在降级了）
- `app/geo/chinaz.py`：站长之家数据，"只作诊断参考，不参与核心评分"

## 5. 三份已发给 SEM/SEO/GEO 开发窗口的任务说明

这三份已经分别发给对应模块的开发窗口，**驾驶舱的指标层完全依赖它们的产出**。截至本次交接，尚未收到任何一个窗口的完成反馈，接手方需要主动跟进。

### 5.1 共享契约（三个窗口收到的是完全一致的一份，不能各自变形）

```
任务(Task)最小字段：
id, module(sem/seo/geo), action_type, title(人话标题),
params(object), status(open/in_progress/done/cancelled),
created_by(cockpit或user_id), assignee_role,
completion_evidence(指向一个真实指标变化，不是自己打勾),
created_at, updated_at

指标(Metric)最小契约：
每个模块暴露一个只读"指标快照"接口，返回 {metric_key, value, unit, as_of, trend_7d} 的列表
metric_key 命名规范：模块.类别.名称，例如 sem.spend.budget_utilization_pct
trend_7d 格式：{direction: up/down/flat/null, change_pct: number/null, change_abs: number/null}
　　——数据不足7天历史时整个 trend_7d 填 null，不要填 0
每个指标必须配一句话文档说明口径
```

### 5.2 SEM 窗口任务

1. 补通用任务/工单机制（参考 GEO 现成的 `action-tickets` 模式），按共享任务契约实现
2. 暴露指标快照接口：花费、预算使用率、有效账户数、待处理审批数、身份冲突客户数
3. 修复 `create_self_approved_approval`（一键资金确认）缺少幂等保护的问题——加客户端幂等键，避免网络重试导致同一笔资金操作执行两次

### 5.3 SEO 窗口任务

0. 先修复三个已知 bug（否则指标层数据是脏的）：
   - `app/seo_ranking_jobs.py` 排名调度器改成每租户独立 session（参考 `seo_monitoring_jobs.py`）
   - `app/api/seo.py` 的 `retry_content_publication` 补兜底 `except Exception`，避免发布任务永久卡在 `publishing`
   - `app/rules/engine.py` 的告警 upsert 补上 `status` 字段刷新（`priority` 字段 SEM 分支已经修过，照抄）
   - `app/security/auth.py` 的 `require_scoped_auth` 租户校验照抄 SEM 分支已修好的写法（SEM 那边用 `isinstance` 判断类型，SEO 还在用有漏洞的字符串 `isdigit()`）
1. 把内容审核状态机改造成通用任务，按共享契约暴露
2. 暴露指标快照接口：核心词排名分布、内容产出速度、图片修复完成度（**完成口径=重新抓取确认，不是审核通过**）

### 5.4 GEO 窗口任务

1. **先做一次独立代码审查**（GEO 是三个模块里唯一没审查过的，而且是驾驶舱最依赖的数据来源之一）——重点看 `app/geo/audit.py` 的诊断评分逻辑和 `competitor-insights` 的可见度对比计算
2. 把现有 `action-tickets` 按共享任务契约做适配（工作量最小，GEO 已经有对应概念）
3. 暴露指标快照接口：AI可见度分数、近7天被提及次数、竞品可见度对比，**时间粒度要和 SEM/SEO 对齐（建议统一按"周"）**

## 6. 接手方现在应该做什么

1. 先完整看一遍 `cockpit/prototype/cockpit-prototype.html`，跑起来点一遍，建立对交互结构的直观理解
2. 跟进第5节三份任务说明的完成情况——这是当前最大的阻塞项，驾驶舱指标层完全依赖它们
3. 三个窗口的接口陆续交付后，把 `cockpit/app/sources.py` 里的 Mock 实现换成真实 HTTP 调用，`main.py`/`contracts.py`/`store.py` 不需要跟着大改
4. 不要跳过阶段2（信号规则先由人定义、验证可信）直接做阶段3/4的对话/执行能力——这条是本次交接里被反复强调的原则，跳过会直接损害产品的可信度

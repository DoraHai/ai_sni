# SEO 上线候选流程核对（2026-10-11）

对象：SEO PR #648 开发候选，基线 ca6a34c28da342327526539579898bfa3baedd87。
以下是代码已实现行为，不代表生产已部署、客户已启用或真实平台已验收。本轮只跑隔离库和模拟供应商；不调用付费接口、不变更客户数据。

## 实际流程与人工边界

| 阶段 | 已实现与触发条件 | 人工/未实现边界 | 代码和测试依据 |
|---|---|---|---|
| 服务准备 | 顾问绑定、站点/模块权益、服务方案、资料与关键词来源校验；服务暂停会阻断后台业务 | 域名、有效资料、顾问分配、服务方向与周期启用需先配置；不能从“已买 SEO”推定所有自动任务开启 | `app/api/seo_service_workflows.py:read_scope/can_operate`；`app/seo_workflow_capabilities.py`；`tests/test_seo_content_workflow.py:test_paused_or_incomplete_plan_cannot_create_work` |
| 启动基础建设 | 顾问 POST `/workbench/onsite-tasks`、work_type=startup，建立 robots、sitemap、代表页面 canonical 清单；可手动保存或请求 AI 草案 | 建单是人工触发；不是自动改网站、完整网站架构评审或全站索引策略验收。canonical 静态检查只能证明该标签匹配 | `app/api/seo_onsite.py:create`；`tests/test_seo_onsite_ai_postgres.py:test_startup_missing_files_remain_unapproved_and_expired_foreign_facts_are_excluded` |
| 月度 TDK/重点关键词/内链 | work_type=monthly + YYYY-MM；最多 3 个 P0/P1 关键词/3 页，强制 landing_page 与已登记页面绑定。生成 Title、Description、Meta Keywords、正文关键词和内链清单 | 月度任务仍需人创建；重点词、页面、链接相关性、锚文本和业务事实需核对。未建立每月自动调用 AI 的站内任务周期；缺项留空阻断审核 | `app/api/seo_onsite.py:create`；`app/seo_onsite_ai.py:validate_result`；`tests/test_seo_onsite.py:test_monthly_plan_binds_keywords_and_finishes_with_real_page_receipt` |
| AI 起草 | 顾问带 durable-v1 协议头提交后只入队；独立调度器每 10 秒领取，候选最多 20 条/并发 2；nonce、站点日限 5 次、来源/身份/版本校验、输出边界与不明终态均持久化 | 不自动提交审批、自动确认事实、自动换模型、自动重试付费或修改官网；unknown 需人工核对。平台保护开关与共享结构须另审，代码存在不等于已经启用 | `app/api/seo_onsite_ai.py:ai_proposal`；`app/seo_onsite_ai_jobs.py`；`tests/test_seo_onsite_ai_postgres.py`、`tests/test_platform_call_guards.py` |
| 审批 | AI 成功仅保存 review 草稿；approve 对当前完整清单哈希留痕；改稿清除旧审批、实施和复检；版本冲突拒绝 | 站内方案当前由有效顾问操作，**没有提交人与审批人必须不同的双人规则**，不得与内容/问答自审门禁混为一谈；若上线要求独立站内审核，这是需另排的差距 | `app/onsite_workflow.py:prepare_change`；`tests/test_seo_onsite_core.py:test_editing_any_proposal_clears_old_review_implementation_and_evidence` |
| 官网实施 | approve 后由人工按批准版本执行；implement 必须带说明且匹配有效审批哈希 | 官网自动修改保持 `website_execution.enabled=false/status=reserved`，没有 CMS 写入器；owner_name 是实施说明，不等于账号分配权限 | `app/onsite_workflow.py:prepare_change`；`app/seo_onsite_ai.py:capabilities`；`tests/test_seo_onsite_core.py:test_review_requires_explicit_values_and_implementation_note` |
| 复检与验收 | 顾问触发 recheck 后真实抓取已限定本站页面，核对 Title/Description/关键词/链接/canonical/robots/sitemap；保留响应摘要及 SHA256。accept 要求当前方案哈希和 24 小时内通过复检 | 触发与业务质量验收仍人工；只检查静态 HTML 内容与地址，不能代替渲染后页面、完整 robots 规则语义、客户认可或搜索效果。完成证据明确不代表排名/收录提高 | `app/api/seo_onsite.py:act`；`app/onsite_workflow.py:recheck/check_item`；`tests/test_seo_onsite_core.py:test_delivery_requires_review_implementation_live_match_and_acceptance`、`test_failed_or_foreign_page_is_not_evidence_and_cannot_complete` |
| 排名和收录监测 | 排名有独立定时采集、国内引擎频率/额度/站点隔离；监测周期可从新鲜度/下跌观测建立跟进任务，等待真实新观测/排名恢复。概览采集有站长之家百度收录估值 | 百度收录数据是域名级供应商估值，不是逐篇已收录证明；indexable 只代表允许索引。未形成每篇内容自动判定“已收录/点击增长”的闭环；供应商凭据、额度、出口许可需满足。概览采集接口不等于日常排名 worker 自动采集该估值 | `app/seo_ranking_jobs.py:collect_daily_seo_rankings`；`app/seo_service_workflows.py:ranking_issues`；`app/api/seo.py:collect_overview_metrics`；`tests/test_seo_scheduler.py`；`tests/test_seo_service_workflows.py:test_rank_drop_requires_observed_recovery_not_just_new_poll` |
| 内容制作、审核、交付 | 内容周期明确启用且到期后自动预留工单/草稿，AI 明确启用后依据有效资料生成；等待内部审核、当前版本客户确认；明确绑定发布记录和后续自动页面证据后完成。多平台多记录要求选择具体交付对象 | 内容周期本身不调用发布供应商；分发渠道/账号与人工回填、失败处理仍需人工。真实平台发布未因本地测试自动验收。内容确认与站内方案 approve 是两种不同流程 | `app/seo_content_workflow.py:reserve_content_workflow/advance_content_workflow/process_site`；`app/seo_content_drafting.py`；`tests/test_seo_content_workflow.py:test_exact_confirmation_then_manual_return_resumes_to_real_page_evidence`、`test_uncertain_or_failed_publications_never_retry_or_capture` |
| 周期建单与月报 | 每分钟扫描已启用内容/网站诊断/排名跟进/月报周期；锁与游标防重复；月报按上月生成并冻结 HTML，等待顾问说明 | **月报自动建单不等于月度站内 TDK 自动建单**。website/monitoring/report/content 周期必须各自开启；默认关闭时不创建或采集。顾问解释、官网实施、验收不自动跳过 | `app/seo_scheduler.py`；`app/seo_service_workflows.py:process_service_site`；`tests/test_seo_service_workflows.py:test_default_cycles_do_not_create_or_collect_anything`、`test_monthly_scheduler_replays_same_period_once_and_does_not_require_customer`；`tests/test_seo_workflow_postgres.py:test_concurrent_cycle_ticks_do_not_duplicate_cursor_or_task` |

## 本候选的可靠度判断

- 对“顾问发起 → 持久化排队 → 单次供应商尝试 → 待审核草案 → 人工实施 → 页面复检”目标，代码链路齐全；专项回归覆盖重复提交、多 worker、进程中断、权限撤销、事实变化、取消、迟到输出、配额、半安装拒绝及调用后记账失败。
- 对“无人值守自动运营、自动改官网、自动证明收录/排名/单篇点击提升”目标，**尚未实现，也不属于此次发布承诺**；不能给出虚构成功率。
- 健康接口只提供真实数据库队列和本进程执行证据。多进程响应可能命中非 owner，必须显示 unverified。跨进程持久化心跳尚未实现；长批次超过 120 秒未完成也可能显示 unverified，不能把它直接当服务宕机。
- `unknown` 数量是站内请求结果待核实，和供应商费用台账不是一一等价。本候选不会强行释放未知费用/并发；共享人工核实协议若尚未审核集成，仍需人工核对供应商记录，不能自行重试。

## 上线前仍要做、无需重做

1. 先确认 SEO/GEO 两个 host adapter 均仅对 AI POST 发送 durable-v1；先前端后后端，旧标签页必须得到可读 409 刷新提示。模块回归不能代替前后端联合验收。
2. 固定提交与 CI 审核后单独批准发布；共享 SQL、运行账号权限、管理开关须分别审核。当前只保证开发候选，不推定线上已具备结构或权限。
3. 生产发布后的只读健康验收需核对服务地址、真实全局超管权限、实际 owner 证据范围及队列；未证实则保留 unverified。仅接口 200 不足以批准自动付费。
4. 真实平台登录/发布、网站实际实施、客户材料与业务质量仍由真人验收；本轮不扩大真人测试或改现有客户数据。
5. 无需重做已有 20260906-45 原型映射、基础只读接口调研或同一轮已经通过的测试；本次只更新变化契约与实现差距。完整接口细节见 `SEO_ONSITE_AI_CONTRACT.md`。

验证记录由 PR 的固定提交和 CI 给出；文档中的测试名称可定位回归，列出能力不等于宣称每个生产条件已满足。

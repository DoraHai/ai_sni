# SEM 智投平台 — 项目背景摘要

> 本文件供 Claude Code 读取项目上下文用。内容整理自与 Claude（Web 端）的历次开发讨论。
> 更新日期：2026-08-14

## 项目定位

多租户百度投放运营工作台。核心闭环：
客户授权百度账户 → 系统同步账户/计划/单元/关键词/报告 → 自动分类和发现问题 → 生成建议 → 人工审核 → 记录调整 → 验证效果 → 生成客户报告。

**技术栈：**
- 前端：Vue 3 + Vite，`frontend/src`
- 后端：FastAPI，`app/main.py`
- 数据库：PostgreSQL + Alembic
- 百度接口封装：`app/baidu/`
- API：`app/api/`
- 自动同步调度：`app/scheduler.py`
- 依赖管理：`requirements.txt`（生产）+ `requirements-dev.txt`（开发/测试），无 `pyproject.toml`

**重要原则：生产当前 `baidu_write_dry_run=True`（演练模式）**
所有写回百度的操作都会先落台账、调用百度接口，但底层 `BaiduAPIClient` 会拦截真实写请求。只有关闭 dry-run 后才会真实生效。**改动涉及写回逻辑时，默认保持这个安全网，除非用户明确要求开启真写。**

---

## 核心模块速查

| 模块 | 页面路由 | 核心文件 |
|---|---|---|
| 首次接入（OAuth授权） | `/onboarding` | `app/api/oauth_baidu.py` |
| 每日盯盘看板 | `/monitor/dashboard` | `app/api/dashboard.py` |
| 异常告警 | `/monitor/alerts` | `app/api/alerts.py`, `app/rules/` |
| 客户画像 | `/monitor/profile` | `app/api/customer_profile.py`, `app/ai/customer_profile.py` |
| 拓词 | `/optimize/expand` | `app/api/expansion.py` |
| 关键词工作台 | `/optimize/keywords` | `app/api/keywords.py`, `frontend/.../KeywordWorkbenchView.vue` |
| 搜索词报告 | `/optimize/search-terms` | `app/api/search_terms.py` |
| 否词管理 | `/optimize/negatives` | `app/api/negatives.py` |
| 调价验证 | `/verify/adjustments` | `app/api/adjustments_verify.py` |
| 投放管理 | `/manage/*` | `app/api/manage.py`, `app/api/ocpc.py` |
| 客户报告 | `/delivery/report` | `app/api/reports.py`, `app/ai/monthly_report.py` |
| AI 助手 | `/assistant` | `app/ai/assistant.py` |
| 账号权限 | `/settings/accounts` | `app/api/auth.py`, `app/api/users.py`, `app/api/roles.py` |

**写回台账（重要，所有真实操作都走这里）：**
- 编排入口：`app/baidu/writeback.py`，各业务 API 调 `apply_*_writeback()`
- 调价专用表：`bid_writebacks`（`app/models/bid_writeback.py`）
- 通用动作表：`writeback_actions`（`app/models/writeback_action.py`），`action_type` 枚举包含 negative/pause/enable/set_match_type 等
- 查询 API：`app/api/writeback.py`

---

## 已完成功能（本轮迭代）

### 1. 报表 xlsx 导出
- 新文件 `app/reports/excel_export.py`，用 openpyxl 生成多 sheet 真 Excel（概览/日趋势/分类/TOP词/设备分布）
- `app/api/reports.py` 的 `/analysis/export`、`/monthly/export` 支持 `format=xlsx`
- 周报/日报不走新路由，复用 `/analysis/export`，前端传不同 `start_date`/`end_date` 即可
- 依赖：`requirements.txt` 加了 `openpyxl==3.1.5`

### 2. 客户画像新增地域占比
- 新表 `kw_region_snapshots`（`app/models/kw_region_snapshot.py`），粒度：`tenant + date + province`（省级汇总，非关键词级，唯一键 `tenant_id+report_date+province`）
- 数据来源：关键词报表 `reportType=2602783`，聚合 `provinceName` 字段
- 同步逻辑接入 `app/scheduler.py`，跟"小时维度"同步任务一起跑，已上生产验证
- `app/ai/customer_profile.py` 的 `gather_profile()` 新增第 7 维 `region`

**注意：** `KwReportSnapshot`（关键词级报表快照）本身没有地域字段，唯一键是 `tenant_id+report_date+keyword_id+device`，不能直接塞地域数据进去（会破坏唯一键语义），这是为什么单独建了 `kw_region_snapshots`。

### 3. 关键词一键操作（工作台）
- 调价：已有（单条+批量）
- 暂停/启用：批量已有；**单条按钮是本轮新加的**
- **改匹配模式：本轮新增**，后端 + 前端都已完成
  - `app/baidu/services/keyword.py` 新增 `update_word_match_type()`
  - `app/baidu/writeback.py` 新增 `apply_match_type_writeback()`，落 `writeback_actions`，`action_type="set_match_type"`
  - 接口：`POST /api/v1/keywords/{keyword_id}/match-type-writeback`
  - 合法组合校验：精确(matchType=1,phraseType=1) / 短语(2,1) / 智能(2,3)，非法组合返回 400
  - 前端：`KeywordWorkbenchView.vue` 加了下拉选匹配模式 + 单条暂停/启用按钮
  - **已在生产 dry-run 冒烟验证通过**

### 4. 异常告警体系扩展
**架构改动（重要）：** `Alert` 表原来的唯一键只支持关键词级（`tenant_id+rule_code+keyword_id+report_date`）。本轮新增 `entity_ref` 字段（格式如 `account:123`、`campaign:456`、`url:短hash`），用两个 **PostgreSQL partial unique index** 分别处理关键词级和实体级告警的幂等去重（比单一复合唯一约束更严谨，避免 NULL 语义问题）：
```sql
ux_alerts_keyword_dedup: UNIQUE(tenant_id, rule_code, keyword_id, report_date) WHERE keyword_id IS NOT NULL
ux_alerts_entity_dedup:  UNIQUE(tenant_id, rule_code, entity_ref, report_date) WHERE entity_ref IS NOT NULL
```
迁移文件：`0059_alert_entity_ref`（**截至本文档更新时，migration 已写好但尚未 upgrade，需要人工确认迁移文件后再执行**）

**新增规则：**
- `BudgetOverrunRule`（`app/rules/budget_overrun.py`，`rule_code=R-BUDGET`）：账户级（查百度 `AccountService.get_account_info` 实时 budget/cost）+ 计划级（`Campaign.budget` vs `KwReportSnapshot` 当日聚合消费）预算撞线，阈值 95%
- `SiteHealthRule`（`app/rules/site_health.py`，`rule_code=R-SITE`）：探测 `Adgroup.pc_final_url`/`mobile_final_url` 可用性和响应时间，**单独接入 hourly 定时任务，不跑在每日 02:00 主同步链路里**（避免网络探测拖慢主流程）

**批量标记已处理：**
- `POST /api/v1/alerts/batch-resolve`，body `{alert_ids: [...]}`
- 前端 `AlertsView.vue` 加了勾选框和批量按钮

**已知遗留（下一轮再做，本轮不做）：**
- "被拒物料"告警（创意/关键词/图片被拒）—— 项目里**完全没有创意（Creative）数据同步**，只有 `app/baidu/services/creative.py` 的写接口（`addCreative`），没有拉取现有创意/审核状态的同步逻辑。要做这个需要先建一条新的创意同步管线（新表 + 百度接口 + 接入每日同步）。
- "物料缺少"告警里的"单元无创意/少于3个/高级样式缺失"——同样依赖创意数据，跟"被拒物料"是同一个前置工作，一起留到下一轮。
- "物料缺少-关键词数量过少"——数据现成（`Keyword` 表本地就有），本轮口头讨论过但还没写代码，是这轮清单里唯一还没交付的低风险项。
- "方案撞线"——已确认这个说法实际指"计划撞线"（口语混淆），不是指 `PriceStrategy`（排名策略表，没有预算概念，只有加价上限/目标排名）。不需要为 `PriceStrategy` 单独做预算告警。

**告警生成方式：** 不是同步时顺手写，是每日 02:00 定时任务里，同步完数据后统一跑 `app/rules/engine.py` 的 `ALL_RULES` 列表生成。手动触发：`POST /api/v1/alerts/run?tenant_id=&target_date=`。

---

## 关键数据模型速查

**`Keyword`**（`app/models/keyword.py`）：包含 `category`（分类：brand/focus/normal/longtail/new）、`price`、`pause`、`match_type`、`phrase_type`、`left_price_guide`、`quality` 等。

**`KwReportSnapshot`**：关键词级报表快照，唯一键 `tenant_id+report_date+keyword_id+device`。字段包括 cost/click/impression/cpc/ctr/avg_rank/conversions/quality_enum 等，**没有地域字段**，有 `raw_metrics: JSONB` 可存原始返回但当前模型没有把地域纳入结构化列。

**`Campaign`**：有 `budget`（计划日预算），**没有** URL 字段。

**`Adgroup`**（也在 `app/models/campaign.py` 里定义）：有 `pc_final_url`、`mobile_final_url`、追踪参数字段。**没有**创意关联（因为没有创意模型）。

**`BaiduAccount`**：**没有**账户预算字段，账户预算通过 `AccountService.get_account_info()` 实时查百度（`budget`/`budgetType`/`balance`/`cost`）。

**`PriceStrategy`**：排名策略表（`price_factor` 加价上限、`target_rank` 目标排名、`campaign_bindings`），**没有预算字段**，不要跟"预算撞线"需求混淆。

**`Alert`**：见上文"异常告警体系扩展"。当前注册规则：`BrandRankRule`(R-14)、`HighCostLowQualityRule`(R-02)、`AIAnomalyRule`(R-AI)、`BudgetOverrunRule`(R-BUDGET)，`SiteHealthRule`(R-SITE) 单独调度不进 `ALL_RULES` 主列表。

**`WritebackAction`** 的 `action_type` 枚举（`app/models/writeback_action.py`）：negative/add_word/remove_negative/pause/enable/set_account_budget/set_campaign_budget/campaign_pause/campaign_enable/adgroup_pause/adgroup_enable/set_adgroup_bid/set_adgroup_url/build_campaign/build_adgroup/build_keyword/build_creative/**set_match_type（本轮新增）**

---

## 开发协作约定

1. **写回百度的功能**，一律走 `app/baidu/writeback.py` 的 `apply_*_writeback()` 模式：先查实体存在性 → 建台账记录（`status="pending"`）→ try 调用百度服务 → 根据 `dry_run` 设置更新状态为 `dry_run`/`success`/`failed` → 失败/异常都要落 `error_msg`，不要吞异常。
2. **改动数据库结构**，一律：先出模型改动 + 迁移文件 → 人工 review 迁移文件 → 确认后再 `alembic upgrade head`，不自动执行。
3. **新增定时任务或数据同步**，涉及外部网络调用（百度接口、URL探测等）时要考虑：是否接入现有 02:00 主同步链路、还是需要独立调度（尤其是耗时不可控的任务，比如网站健康检查）。
4. **每次不确定现有代码结构时**，先去问实际代码（模型定义、API 实现），不要凭猜测写改动方案。
5. **前端改动**，风格要跟现有页面一致（比如批量操作用 `bulk-toolbar` 那套 class，确认弹窗用 `ElMessageBox`）。

---

## 非 SEM 模块（不在这个项目范畴内）

项目还有 GEO、SEO、诊断中心、官网 等模块，**这份摘要和历次讨论都只覆盖 SEM 模块**，其他模块的代码/数据结构未纳入本文档。

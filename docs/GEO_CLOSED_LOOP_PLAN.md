# GEO 闭环方案：从五个工具到一条业务链路

> 承诺：监测 AI 是否提到你 → 发现缺口 → 补内容 → 发布 → 再测量证明提升。

## 推进顺序（商业优先级）

| 序 | 主题 | 解决什么 | 状态 |
|----|------|----------|------|
| 1 | **发布 ↔ 监测归因** | 证明「发了有用」 | ✅ 已落地 |
| 2 | **缺口工作台** | brand_missing → 任务队列 | ✅ MVP 已落地 |
| 3 | **优化期次实体** | 交付/对比有形边界 | ✅ 落库+API+页 |
| 4 | **GEO 开户向导** | 新客户进得来 | ✅ 已落地（含 audit） |
| 5 | **安全 + 异步** | 能卖且不翻车 | ✅ 小修+异步主路径；生产收口持续 |

## 断点与对策

### 断点一：发布与监测无关（最致命）

**对策**

1. 自有域集合 = 渠道 `base_url` ∪ **已发布 URL 域名**（动态，不依赖手填）
2. 快照落库时反查 `geo_publications.published_url`，写入 `matched_publication_ids`
3. 内容任务 API：`GET .../content-tasks/{id}/impact`  
   - 发布后 N 天引用命中次数  
   - 相关意图词提及率：发布前窗 vs 发布后窗  
4. 前端任务编辑器展示「发布后效果」卡

### 断点二：新客户进不来

**对策（下一迭代）**

- GEO 开户向导：官网 URL → 业务线候选 → 意图词 → 事实卡草稿 → 引擎建议  
- 复用：`fetch_page_text`、expand-candidates、promote-candidates、事实创建 API

### 断点三：缺口不会自动变成工作

**对策**

- `GET /api/v1/geo/gap-workbench`：聚合 `brand_missing`，按优先级/业务排序  
- 批量建任务 + 概览待办数（已有 `prompts_brand_missing`）  
- 前端「缺口工作台」页

### 结构问题

| 问题 | 对策 |
|------|------|
| 任务无业务维度 | `geo_content_tasks.business_id` 可空；生成时从 prompt.unit 反填；日指标「未分类」桶后续 |
| 期次无实体 | `geo_optimization_periods`：时间窗+业务+基线 meta+期末 meta |
| 模拟样本 | 已有 sample_composition 标注；商业定位另议 |

## 商业定位（需产品拍板）

| 选项 | 含义 |
|------|------|
| A 平台统一采买 | 各引擎真 Key 对客户透明 |
| B 第三方/爬虫 | 监测不依赖客户 Key |
| C 明确「模拟评估」 | 报表默认标注模拟，交付合同写清 |

在拍板前：**交付与报表必须展示样本构成**（已做）。

## 信息架构

- **主轴（下一迭代 UI）**：优化业务详情一屏串五段  
- **专家菜单**：保留现有模块页  

## 安全/工程硬伤（本迭代小修）

- 权限：`ai-settings` / `channel-polish` / `metrics` / `gaps` / `periods` 归入 `geo.content`  
- 自审：`reviewed_by != submitter`（配置可关）  
- Score 门禁：文档标明默认关；配置项已存在  

## 本迭代交付清单

- [x] 方案文档  
- [x] 自有域含发布 URL  
- [x] 快照 matched_publication_ids + 匹配逻辑  
- [x] 任务 impact API + 编辑器卡片  
- [x] 缺口工作台 API + 页  
- [x] 期次实体 + 基础 API  
- [x] 权限映射修复  
- [x] 自审禁止  

## 已落地说明（2026-08-11）

| 能力 | 位置 |
|------|------|
| 自有域 = 渠道 base_url ∪ 发布 URL 域名 | `_own_domains_for_tenant` + `attribution.py` |
| 快照反查 publication | `matched_publication_ids` 列；创建/更新快照、巡检落库时写入 |
| 任务效果 | `GET /api/v1/geo/content-tasks/{id}/impact`；编辑器「发布后效果」卡 |
| 缺口工作台 | `GET /gap-workbench`、`POST /gap-workbench/create-tasks`；`/geo/gaps` |
| 优化期次 | `geo_optimization_periods`；CRUD/close；`/geo/periods` |
| 任务业务维度 | `geo_content_tasks.business_id`（从 prompt.unit 反填） |
| 权限 | `ai-settings` / `channel-polish` / `gap-workbench` / `optimization-periods` / metrics → `geo.content` |
| 自审自批 | `review_submitted_by` + `apply_decision` 拒绝同人通过 |

## 下一迭代交付（2026-08-11 已落地）

| 能力 | 位置 |
|------|------|
| GEO 开户向导 | `POST /onboarding/preview` + `/apply`；`/geo/onboarding` |
| 业务详情一屏 | `GET /optimization-businesses/{id}/dashboard`；前端页 `/geo/businesses/:id` 已下线，改走 `/geo/brand` |
| 生成/推送异步 | `geo_async_jobs`；generate/push-batch `run_async`；前端轮询 |
| 引擎商业定位 | `monitoring_stance`：simulation / hybrid / real_only；引擎页选择器 |

产品默认 **hybrid（混合）**：有 Key 真采样、无 Key 模拟，报表强制样本构成标注。

## 工程加固（2026-08-12+）

| 能力 | 说明 |
|------|------|
| query 禁用 API Key | `ADMIN_API_KEY_QUERY_ENABLED`；生产 `prod_guard` 强制 false |
| API Key 租户绑定 | `ADMIN_API_KEY_TENANT_ID` 可选 |
| 自审可配置 | `GEO_ALLOW_SELF_REVIEW`（默认 false） |
| 异步 stale 回收 | pending/running 超时 failed + 释放 generating/adapting |
| 日指标未分类桶 | scope_key=`unc`（无 unit 的意图词） |

### 工程加固（2026-08-12 下一批）

| 能力 | 说明 |
|------|------|
| 进程重启恢复 | `recover_jobs_on_startup`：running→failed，pending 未过期 requeue |
| 缺口 SLA | `GEO_GAP_SLA_DAYS`；缺口台字段 + ops 告警 +「超 SLA 建任务」 |
| 归因回填 | `POST /attribution/backfill`；引用分析页按钮 |
| 默认主入口 | `geo.content` → `/geo/overview` |

## 口径/证明力计划（2026-08-12 已推进）

| 批次 | 项 | 状态 |
|------|-----|------|
| 前置 | 迁移 0062：period_id + sample 回填 | ✅ |
| 前置 | 四路径同值安全网 `test_geo_metric_parity` | ✅ |
| W1 | `compute_metrics` 统一上海日口径 | ✅ 期次对比/业务详情/交付/竞品日趋势 |
| W4 | http/https 归一；impact 样本量+外溢+对照；回填游标 | ✅ |
| W2 | tasks/pubs/snapshots.period_id 写入 active 期次 | ✅ 写入 + 消费方 period_id 锁窗/固化 pack |
| W3 | real_only 不降级 persona（patrol skip） | ✅ + 引擎页跳过预览 |
| W5 | run_async 默认 true；前端轮询对齐 45min | ✅ |
| W6 | ops 角色降权 / 自助开户 / unc UI | ⏳ unc 露出；RBAC/开户未做 |

### 仍待

- W2 消费方：period_id 入参锁死对比/交付窗 + 关闭固化 pack ✅
- W3 报表按 stance 强制排除模拟 + 引擎页跳过预览 ✅
- W6 API Key 降权、租户自助开通 ⏳；unc 桶露出 ✅
- Celery/Redis（触发条件未到）

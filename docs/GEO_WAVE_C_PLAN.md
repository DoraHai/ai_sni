# GEO Wave C：竞品 / 评价 / 简单可见度分（方案 A）

> 状态：已实现 · 分支 `feature/geo-wave-c`（含未提交 B3）  
> 前置：Wave B3 复核闭环

## 1. 目标

在人工快照上补齐竞品与评价标注，并给出**可解释的简单分**（非加权伪科学引擎）：

**登记快照时标注竞品名 + 我方位置 + 情感 → 竞品/评价页聚合 → 概览展示提及率与引擎覆盖。**

## 2. 非目标

- DeepSeek 自动抽取竞品/情感（留给 C+）
- 可配置加权总分 / 排名看板
- 独立竞品主数据表 / 评价维度表
- 多模型巡检、因果归因

## 3. 数据（扩展既有快照，不新建表）

`geo_answer_snapshots` 新增：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `competitors` | JSONB | 竞品名字符串列表，默认 `[]` |
| `brand_position` | String(16) | `first` / `mentioned` / `absent` / `unknown`（默认） |
| `sentiment` | String(16) | `positive` / `neutral` / `negative` / `unknown`（默认） |

## 4. API

- 扩展 `POST/PATCH /answer-snapshots` 与列表 payload 读写上述字段
- `GET /competitor-insights`：按竞品名聚合（出现次数、关联提问数、引擎）
- `GET /evaluation-insights`：按情感/位置聚合计数 + 最近快照列表
- `GET /content-stats` 增补：
  - `visibility_mention_rate`：有快照中 `mentions_brand=true` 占比（0–1，无快照为 null）
  - `visibility_engines_covered`：至少一条快照的 distinct engine 数
  - `snapshots_with_competitors`：competitors 非空的快照数

## 5. UI

- `visibility.html`：竞品（逗号分隔）、我方位置、情感
- `competitors.html`：聚合表 + 深链可见度
- `evaluation.html`：情感/位置计数 + 最近快照
- `dashboard.html`：提及率、引擎覆盖卡片

## 6. 验收

- [x] 保存快照可带竞品/位置/情感；列表可见
- [x] 竞品页按名称聚合出现次数
- [x] 评价页展示情感与位置分布
- [x] 概览提及率 = 提及快照 / 全部快照；引擎覆盖为 distinct engine
- [x] 不做加权总分、不自动抽取

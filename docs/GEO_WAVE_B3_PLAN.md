# GEO Wave B3 方案：可见度复核闭环

> 状态：已实现 · 分支 `feature/geo-wave-b3-recheck`  
> 前置：Wave B/B2（人工快照 + 引擎/信源）

## 1. 目标

在人工快照之上补齐运营闭环：

**选题 brand_missing → 写稿发布 → 复测（粘贴或 DeepSeek 草稿）→ 提及清标签 / 未提及加回 → 概览与提问列表可见状态。**

## 2. 非目标

- 多模型定时巡检  
- 可见度加权总分、竞品/评价（Wave C）  
- 发布→提及因果归因  
- 探测结果自动落库  

## 3. 交付

| 项 | 说明 |
| --- | --- |
| 待复核队列 | `content-stats.prompts_brand_missing` / `prompts_need_recheck` + 概览卡片 |
| 提问增强 | `GET /prompts?tag=` + last_snapshot_* 字段 |
| 标签对称 | mentions=true 去 brand_missing；false 加回 |
| 发布 CTA | 回填成功 →「去登记可见度」 |
| DeepSeek 探测 | `POST /answer-snapshots/probe` 草稿，人确认后 POST 入库 |

## 4. 验收

- [x] 概览可点「未提及品牌 / 待复核」进入对应列表  
- [x] 提问列表可见最近观测；可按 tag 过滤  
- [x] 快照提及否会加减 `brand_missing`  
- [x] 发布回填后可一键去可见度  
- [x] DeepSeek 探测预填正文（无 Key 时明确降级提示）  

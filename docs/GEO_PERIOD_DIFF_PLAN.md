# GEO 期次对比（可见度窗口 + 拓词跨期）

> 状态：可合并 · 分支 `cursor/geo-period-diff-21de`  
> 前置：Wave C / D0 / D4 / citation insights · Phase 2 发布连接器仍后置

## 目标

1. **可见度 before/after**：按 `captured_at` 两个窗口对比提及率与自有域引用率（未测=`null`）。
2. **拓词 vs 上次**：持久化 expand run，候选打 `vs_last_run` 徽标。

## 非目标

- 发布→可见度因果归因
- 保存命名 cohort / 多引擎自动采样
- 拓词「消失词」列表 / 任意历史 run 对比
- 发布连接器 Phase 2

## 数据 / API

- 新表 `geo_expand_runs`（migration `0050`），每租户保留最近 20 次
- `GET /visibility-period-diff?before_from&before_to&after_from&after_to`
- `POST /prompts/expand-candidates`：默认 `persist=true`，返回 `run_id` / `last_run_id` / `new_vs_last_count` / `vs_last_run`

## UI

- 概览：期次对比卡片（默认近 28 天对半切）
- 提问监控拓词表：库内徽标 +「新↑ / 仍在」

## 验收

- [x] 窗口空 / 无自有域 → rate 为 null，delta 为 null
- [x] 探测题不进可见性提及率
- [x] 第二次拓词出现相对上次计数与徽标
- [x] 持久化不自动写入问题库
- [x] pytest 覆盖

# GEO C+ · 快照字段 AI 标注建议

> 状态：可合并 · 分支 `cursor/geo-cplus-suggest-fields-21de`  
> 前置：Wave C 人工标注字段 + 正文 URL 抽取

## 目标

对粘贴/探测的回答正文给出 **竞品 / 我方位置 / 情感 / 提及** 建议，运营确认后再保存；不自动写库。

## 非目标

- 无人值守批量巡检写库
- 加权可见度总分
- 发布连接器 Phase 2

## API / 行为

- `normalize_suggest_payload`：规范化 LLM JSON + 启发式品牌提及 + URL 抽取
- `POST /answer-snapshots/suggest-fields`：对已有正文出建议（需 AI Key；`use_llm=false` 仅启发式/URL）
- `POST /answer-snapshots/probe`：探测回答时一并返回建议字段
- UI：可见度页「AI 标注建议」；探测成功后自动填表

## 验收

- [x] 建议字段经 normalize，非法值落到 unknown / []
- [x] 竞品建议不包含本品牌名
- [x] 不写库直至「保存快照」
- [x] pytest 覆盖 normalize / heuristic

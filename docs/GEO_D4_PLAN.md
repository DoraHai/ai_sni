# GEO D4 · 拓词候选

> 状态：实现中 · 分支 `cursor/geo-d4-expand-candidates-e856`  
> 参考：`_refs/geolook/scripts/expand.py` · 前置 D0–D3（已合 main）

## 范围

- 模块：`app/geo/content/expand.py`（百度/Google 下拉、GROUP_CUES 七组、模板问句）
- API（**不入库**直到显式确认）：
  - `POST /prompts/expand-candidates` — 词根×修饰 → 候选列表（标 `in_bank`）
  - `POST /prompts/promote-candidates` — 勾选批量写入，`source=expand`
- 词根：请求 `roots` / `competitors` / `products`，或 `seed_from_tenant` 用品牌名+行业
- UI：`prompts.html` 拓词面板（勾选入库）
- **无新表**（候选 ephemeral；跨期 diff 留给后续）

## 非目标

- 自动改问题库
- SEM KRService / `keyword_candidates` 复用
- LLM 问句转写（模板即可；有 Key 时后续可加）
- expand.json 期次 diff 徽标

## 验收

- [x] stub suggest 单测：过滤导航词、分组、in_bank
- [x] expand / promote API 挂在 `geo.content`
- [x] 提问机会池可拉取候选并勾选入库
- [x] `source` 支持 `expand`

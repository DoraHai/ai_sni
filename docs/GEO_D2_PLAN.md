# GEO D2 · 可抽取块 + 编造风险 lint

> 状态：实现中 · 分支 `cursor/geo-d2-extractable-lint-e856`  
> 参考：`_refs/geolook`（`audit.py` RE_* / `generate.lint_draft`）· 前置 D0/D1

## 范围

- **可抽取块**：定义 / 数字事实 / 对比 / 操作步骤 / FAQ  
  - 模块：`app/geo/content/extractable_blocks.py`
  - 写入页面审计 findings（`block_*`）与 snapshot
  - 内容规则：`numbers_extractable` / `comparison_extractable` / `howto_extractable`（定义与 FAQ 沿用既有规则）
  - 一键补丁：缺块时插入模板段
- **编造风险 lint**：占位竞品名、未核实数字、可疑年份  
  - 模块：`app/geo/content/draft_lint.py`
  - 规则：`fabrication_lint`（仅 **高** 级阻断就绪）
  - API：`POST /content-tasks/{id}/check` 附带 `lint` + `blocks`；`POST .../lint` 只扫描不改状态
  - 编辑器：可抽取块徽章 + 编造风险列表 +「仅扫编造风险」

## 非目标

- 不 fork GeoLook CLI/UI
- 不改 D3 人工核验工作流（下一切片）
- 中/低 lint 仅提示，不阻断发布就绪

## 验收

- [x] 五块检测与 issue_code 映射（NO_DEFINITION 等）
- [x] 审计报告含 `blocks` / `block_issue_codes`
- [x] 规则门禁含数字/对比/步骤 + 高风险编造阻断
- [x] check/lint API 与编辑器展示
- [x] `pytest` 含 `test_geo_d2_extractable_lint`

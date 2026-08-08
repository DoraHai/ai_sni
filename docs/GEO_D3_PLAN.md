# GEO D3 · 验收工单 MVP

> 状态：实现中 · 分支 `cursor/geo-d3-verify-mvp-e856`  
> 参考：`_refs/geolook/scripts/verify.py` · 前置 D0–D2  
> 迁移：`0046_geo_action_tickets`

## 范围

- 表 `geo_action_tickets`：诊断整改工单 + `acceptance_type` / `acceptance_check` / evidence / progress
- Checker DSL（单页诊断 + 媒体，**不做** metrics 全量验收）：
  - `site.has_llms_txt` / `pages.has_jsonld`
  - `finding.passed:<code>`
  - `pages.block:<definition|numbers|comparison|howto|faq>`
  - `media.any_published` / `media.published:<channel_key>` / `media.placement_published:<id>`
- API：
  - `POST /audits/{id}/tickets` 从 advice/失败项生成工单
  - `POST /audits/{id}/verify` 可选重抓后批量验收
  - `GET|POST /action-tickets`、`PATCH`、`POST .../verify`
- UI：`geo/tickets.html`（侧栏「验收工单」）

## 非目标

- 全站 crawl / `metrics.*` / `external.any` 验收
- GeoLook `tasks.json` 文件仓
- 代理商交付包

## 验收

- [x] 失败 finding → auto check 映射（llms/schema/blocks…）
- [x] 重抓后通过 → `done`；回归 → `reopened`
- [x] 媒体 published+URL 可单独建工单并验收
- [x] `pytest` 含 `test_geo_d3_verify`
- [x] alembic `0046_geo_action_tickets`

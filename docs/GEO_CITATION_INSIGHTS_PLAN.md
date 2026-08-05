# GEO 引用域名聚合（Citation Insights）

> 状态：可合并 · 分支 `cursor/geo-citation-insights-21de`  
> 前置：Wave C 快照 `cited_urls` + D1 `CHANNELS_CN` 阵地蓝图

## 1. 目标

把人工快照里已登记的引用 URL，聚合成**可解释的域名看板**，并对照国内阵地蓝图权重：

**cited_urls → 去 www 主机名 → 按域名计数 / 提问 / 引擎 → 可选蓝图阵地标签 → 概览覆盖计数。**

## 2. 非目标

- 从回答正文自动抽取 URL（留给后续）
- 公众号 / CMS 一键发布连接器（Phase 2）
- DeepSeek 自动抽取竞品/情感（C+）
- 导入 GeoLook 全量 CN-GEO 语料做大盘对照
- 加权「引用健康分」总分

## 3. API

- `GET /citation-insights?tenant_id=`
  - `items[]`: `domain`, `cite_count`, `prompt_count`, `engines`, `sample_urls`, `is_own_domain`, 蓝图字段
  - `snapshots_with_citations` / `distinct_cited_domains`
  - `own_domains`：启用中的官网/文档渠道 `base_url` 解析出的域名
  - `own_domain_cite_rate`：含引用快照中至少命中一个自有域的占比；未配置自有域时为 `null`
- `GET /content-stats` 增补：`snapshots_with_citations`、`distinct_cited_domains`

## 4. UI

- `citations.html`：域名表 + 覆盖摘要
- 侧栏「智能监测 → 引用域名」
- 概览卡：含引用 URL / 引用域名数

## 5. 验收

- [x] 快照带 cited_urls 后域名按出现次数聚合
- [x] 无引用时返回空列表，不造假零指标
- [x] 已知 CN 主机可打上蓝图阵地与 national 参考
- [x] 官网 base_url 配置后可算自有域引用率
- [x] pytest 覆盖 domain 解析与蓝图匹配

# GEO 客户展示名对照

> 系统内部 API 字段名保持英文；**UI / 交付 Markdown** 使用下表展示名。  
> 日期：2026-08-07

| 系统现状 / 内部概念 | 客户展示名 | 备注 |
| --- | --- | --- |
| 机会词 / prompts | **优化意图词** | 可挂 `unit_id` |
| 引擎 / tracking engines | **引擎** | — |
| 可见性提及率 `visibility_mention_rate` | **品牌提及率** | 分母排除品牌探测题；无样本为「—」 |
| 品牌认知率 `probe_recognition_rate` | **品牌点名认知率** | 仅探测题；可选分列 |
| 引用域名 / cite_count | **AI 引用次数** | 快照 `cited_urls` 聚合；需说明口径 |
| 竞品分析 | 竞品分析 | — |
| 内容任务 / content-tasks | **优化文章** / 内容任务 | 主展示「优化文章」 |
| （新建）业务 | **优化业务** | 三级顶层 |
| （新建）单元 | **优化单元（关键词）** | 挂业务下 |

## 三级结构

```text
优化业务 → 优化单元（关键词）→ 优化意图词 → 优化文章
```

## AI 引用次数口径（对客户说明）

- **citation_count**：回答快照中引用 URL 的出现总次数  
- **distinct_cited_domains**：去重后的独立被引域名数  
- **非**全网抓取；仅系统内已登记的回答快照  

## 相关页面

- `/geo/businesses` · `/geo/prompts` · `/geo/overview` · `/geo/deliverables` · `/geo/citations`

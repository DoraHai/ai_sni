# GEO Wave B 方案：可见度（人工快照 MVP）

> 状态：已实现（人工快照 MVP）· 分支 `feature/geo-wave-b-visibility`  
> 前置：Wave A 已合入 `main`（内容闭环 + 诊断桥）

## 1. 目标

运营可对某个**机会问题**粘贴 ChatGPT / DeepSeek 等回答快照，标记是否提及品牌，并在「AI 可见度」页回顾——闭合设计文档中的人工对照步骤。

## 2. 非目标（本切片不做）

- 多模型自动巡检 / AnswerSnapshot 自动化抓取  
- 引擎 CRUD（`engines.html` 继续占位）  
- 可见度加权总分 / 排名看板  
- 竞品 / 评价产品化  
- 发布 → 提及的因果归因  
- Dashboard 假数据图表  

## 3. 数据模型

**表 `geo_answer_snapshots`**

| 列 | 说明 |
| --- | --- |
| tenant_id | 租户 |
| prompt_id | FK → geo_prompts |
| engine | chatgpt / deepseek / doubao / perplexity / other |
| raw_text | 粘贴的回答全文 |
| captured_at | 观测时间 |
| mentions_brand | 运营勾选：是否提及品牌 |
| cited_urls | JSONB 链接列表（可选） |
| note | 备注 |
| created_by / created_at | 审计 |

**副作用：** 创建或更新且 `mentions_brand=true` 时，若 prompt.tags 含 `brand_missing`，则移除该标签。

## 4. API

```text
GET    /api/v1/geo/answer-snapshots?tenant_id=&prompt_id=
POST   /api/v1/geo/answer-snapshots
PATCH  /api/v1/geo/answer-snapshots/{id}?tenant_id=
```

鉴权：复用 `geo.content`（与 prompts/facts 同域）。

## 5. UI

| 页 | 行为 |
| --- | --- |
| `visibility.html` | 实装：选机会问题 + 粘贴表单 + 快照列表 |
| `prompts.html` | 行内「可见度」深链 `?prompt_id=` |
| engines / media / competitors / evaluation | 保持 Wave B/C 占位 |

## 6. 切片排期

| 切片 | 交付 |
| --- | --- |
| B0 | migration 0038 + model |
| B1 | schemas + routes + tag 副作用 |
| B2 | visibility UI + geo-api 客户端 |
| B3 | prompts 深链 + 文档/单测 |

## 7. 验收

- [ ] 选 prompt → 粘贴回答 → 勾选提及品牌 → 列表可见  
- [ ] prompts「可见度」带 `prompt_id` 过滤  
- [ ] `mentions_brand=true` 清除 `brand_missing`  
- [ ] engines 等页仍为开发中  

## 8. 本地联调

见 `docs/LOCAL_GEO_DEMO.md`「可见度人工快照」一节；端口仍为 API **8011**、静态 **5176**。

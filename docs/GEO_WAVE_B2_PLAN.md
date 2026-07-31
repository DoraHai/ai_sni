# GEO Wave B2：可见度闭环补齐 + 引擎/媒体策略

> 状态：已实现 · 分支 `cursor/geo-wave-b2-remaining-b24b`  
> 前置：Wave B 人工快照 MVP（`geo_answer_snapshots`）

## 1. 目标

在人工快照 MVP 之上补齐运营可用闭环：

1. **鉴权修正**：`answer-snapshots` 归 `geo.content`
2. **真实可见度计数**：概览展示快照总量 / 品牌提及率（无假图表）
3. **快照可编辑**：列表内切换「是否提及品牌」
4. **引擎管理页**：租户勾选监测引擎（供可见度表单下拉），不做自动巡检
5. **媒体/信源策略页**：权威信源布局清单（计划→已铺设 URL），不做竞品看板

## 2. 非目标

- 多模型自动抓取 AnswerSnapshot  
- 可见度加权总分 / 排名伪科学看板  
- 竞品分析 / 评价分析产品化（仍属 Wave C）  
- 发布→提及因果归因  

## 3. 数据

### `geo_tracking_engines`

| 列 | 说明 |
| --- | --- |
| tenant_id | 租户 |
| engine_key | chatgpt / deepseek / … |
| display_name | 展示名 |
| enabled | 是否出现在可见度表单 |
| note | 监测备注 |
| sort_order | 排序 |

首次 GET 若为空，写入默认引擎集。

### `geo_media_placements`

| 列 | 说明 |
| --- | --- |
| tenant_id | 租户 |
| name | 信源/媒体名 |
| channel_type | website / zhihu / wechat / news / wiki / other |
| target_url | 目标页或栏目 URL（可选） |
| authority_note | 为何布局该信源 |
| status | planned / in_progress / published / archived |
| published_url | 已铺设 URL |
| priority | 排序权重 |
| related_prompt_id | 可选关联机会问题 |

## 4. API

```text
GET/PUT  /api/v1/geo/tracking-engines?tenant_id=
GET/POST /api/v1/geo/media-placements?tenant_id=
PATCH    /api/v1/geo/media-placements/{id}?tenant_id=
GET      /api/v1/geo/content-stats  # 增 snapshot_* 字段
```

## 5. 验收

- [x] 仅有 `geo.content` 时可读写 answer-snapshots  
- [x] 概览显示快照数与品牌提及数，可跳转可见度页  
- [x] 可见度列表可切换 mentions_brand，并清除 brand_missing  
- [x] engines 页可启用/停用引擎；可见度下拉只显示 enabled  
- [x] media 页可建信源布局并回填 published_url  
- [x] competitors / evaluation 仍为开发中  

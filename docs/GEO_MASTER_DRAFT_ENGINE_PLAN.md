# GEO 母稿引擎强化设计（Content Brief / Fact Retrieval / GEO Score / AI Reviewer）

> 文档日期：2026-08-05  
> 状态：**P0 + P1a + P2 + P3 已实现**（Score/Reviewer 门禁默认关闭，env 可开）  
> 相关实现：`brief.py` · `brief_suggest.py` · `fact_retrieve.py` · `geo_score.py` · `ai_reviewer.py` · `generate_article.py`

---

## 已实现（P0 / P1a）

### P0 Content Brief v2

- `task.brief` 扩展策略字段：`ai_question`、`not_recommended_reasons`、`info_gaps`、`recommend_when`、`competitors`、`must_cover`、`source_bar`、`strategy_notes`
- **生成门禁仍只要求 v1 五字段**（兼容）
- `GET /content-brief-catalog` 返回 schema_version=2 与 gaps 枚举
- `POST /content-tasks/{id}/suggest-brief`：启发式 + 可选 LLM；默认 merge 不覆盖已填
- 生成 prompt 注入 `brief_strategy_block` + content_type 章节建议
- 编辑器：策略字段 +「AI 建议 Brief」

### P1a Fact 召回

- `POST /content-tasks/{id}/retrieve-facts`：关键词打分 top-k（无向量）
- `POST /content-tasks/{id}/retrieve-facts/apply`：绑定选中 facts
- `auto_bind` 可选（limit≤20）
- 编辑器：「召回事实」「绑定召回 Top」

### 测试

- `tests/test_geo_brief.py` · `tests/test_geo_brief_suggest.py`

---

## P2 GEO Score（已实现）

- `compute_geo_score`：structure / evidence_use / authority / comparison / gap_coverage / extractability
- `POST …/check` 响应与 `rule_result` 写入 `geo_score`、`geo_subscores`、`geo_actions`
- 环境变量：`GEO_SCORE_GATE`（默认 false）、`GEO_SCORE_THRESHOLD`（默认 60）
- 开启 gate 时：check 的 ready 与 publish 可被低分阻断

## P3 AI Reviewer（已实现）

- `POST …/ai-review`：`persist` 默认 true，写入 `rule_result.ai_review`
- issues：`block|warn`；`GEO_AI_REVIEW_GATE=true` 时 block 项阻断 publish
- 无 LLM 配置 → 503（不伪造成空通过）

## 仍可选

| 切片 | 内容 |
| --- | --- |
| **P2.5** | 多模型候选 + Score 择优 |

### 目标四道门

| 门 | 状态 |
| --- | --- |
| G0 生成前 brief+事实 | ✅ brief v2 建议 + 召回 |
| G1 生成中模板 | ✅ 策略注入 |
| G2 生成后 Score | ✅ P2（默认 warn） |
| G3 发布前 Reviewer | ✅ P3（默认不挡；可开 gate） |

### 原则

- 叠在现有 `facts → generate → check → variants` 上，不推倒  
- 先策略与质量，后社交 OAuth  
- 禁止改 `app/baidu/**`

---

## 修订记录

| 日期 | 说明 |
| --- | --- |
| 2026-08-05 | 设计初版 |
| 2026-08-05 | P0+P1a 落地实现 |
| 2026-08-05 | P2 GEO Score + P3 AI Reviewer 落地 |

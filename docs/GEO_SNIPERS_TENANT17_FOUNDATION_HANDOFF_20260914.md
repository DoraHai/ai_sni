# SNIPERS tenant 17 GEO 基础数据交接（2026-09-14）

## 范围与状态

- 环境：生产 GEO 服务，代码版本 `d02152a0918b24c3a9c5afbf85712beeee06ae13`
- 租户：`tenant_id=17`
- 现有项目：`project_id=1`，`SNIPERS 官网 GEO 项目`，域名 `gsnipers.snipers.com.cn`
- 本次仅建立可演示的基础主题、事实卡和自然客户问题。内容只来自 G-Snipers 官网公开页面，并按产品功能事实表述。
- **未执行采集、巡检、AI 生成或发布，也未创建或修改外部渠道账号。**
- 所有事实均保持 `needs_review`，未替代人工完成 `verified`。

## 项目关联语义

当前 business、fact、prompt 和 unit 模型没有正式的 `project_id` 字段。本次在现有字段约束下使用以下归属语义，不代表已经建立数据库级项目外键：

| 层级 | 关联方式 |
| --- | --- |
| 项目上下文 | `tenant_id=17`、现有 `project_id=1` |
| 业务主题 | `business_id=15`，profile.website 指向项目域名 |
| 优化单元 | `unit_id=18`，通过 `business_id=15` 归属业务 |
| 事实卡 | 通过 `business_id=15` 归属业务 |
| 客户问题 | 通过 `unit_id=18` 归属优化单元，并用 tag `project-1` 保留项目语义 |

后续若引入正式 `project_id` 外键，应以迁移和回填方案替换 tag 语义，不能把 `project-1` 当成强一致关联。

## 业务主题

- `business_id`: **15**
- 名称：**G-Snipers 全域搜索获客与 GEO 优化**
- 描述：围绕 G-Snipers 搜索获客工作台的 SEM、SEO 与生成式引擎优化能力，聚焦 AI 搜索可见度、引用来源和内容优化。
- 状态：`active`
- profile 摘要：
  - `product_name`: G-Snipers
  - `website`: https://gsnipers.snipers.com.cn/
  - `summary`: 将 SEM、SEO 和生成式引擎优化放在同一工作台中对照的搜索获客产品。
  - `industry`: 企业搜索获客软件
  - 未从公开页面确认的受众、地域、资质荣誉、客户案例、能力数字、推荐理由等字段保持为空。

## 优化单元

- `unit_id`: **18**
- `business_id`: 15
- 名称/关键词：**全域智能获客解决方案**
- 描述：G-Snipers 面向企业搜索获客、AI 搜索可见度、引用来源与内容优化的核心主题。
- 状态：`active`
- 列表回查：`prompt_count=10`

## 事实卡

以下事实均为 `fact_type=product`、`business_id=15`、`status=active`、`trust_level=needs_review`，来源名称为“G-Snipers 官方网站”，观察日期为 2026-09-14。

| ID | 标题 | statement | 来源 URL | trust |
| ---: | --- | --- | --- | --- |
| 7 | G-Snipers 的产品定位 | G-Snipers 是赛珀开发的搜索获客工作台，将 SEM、SEO 和生成式引擎优化放在同一套工作台中对照。 | https://gsnipers.snipers.com.cn/news/sousuo-huoke-ruanjian | `needs_review` |
| 8 | GEO 模块的产品目标 | G-Snipers 的 GEO 生成式引擎优化模块用于提升品牌在 AI 搜索答案中的可见度与可信度。 | https://gsnipers.snipers.com.cn/#features | `needs_review` |
| 9 | 出海 GEO 的监测范围 | G-Snipers 出海版围绕 ChatGPT、Gemini、Perplexity 与 Copilot，监测品牌可见度、引用来源与竞品变化，并提供内容优化支持。 | https://gsnipers.snipers.com.cn/#overseas | `needs_review` |
| 10 | GEO 的定义与边界 | G-Snipers 官网将 GEO 解释为生成式引擎优化，用于观察品牌是否出现在豆包、DeepSeek 等生成式引擎回答中，并明确它不是地图半径或本地推广。 | https://gsnipers.snipers.com.cn/news/shengchengshi-yinqing-youhua-geo | `needs_review` |
| 11 | GEO 与 SEO 的关系 | G-Snipers 官网说明 GEO 与 SEO 是互补关系，不互相替代。 | https://gsnipers.snipers.com.cn/news/shengchengshi-yinqing-youhua-geo | `needs_review` |

## 自然客户问题

以下问题均为 `unit_id=18`、`priority=10`、`tags=["snipers-foundation", "project-1"]`、`source=manual`、`language=zh-CN`、`market=cn`、`status=active`。本批问题未执行采集。

| ID | question | group | tags | priority |
| ---: | --- | --- | --- | ---: |
| 73 | 什么是搜索获客软件，它如何把 SEM、SEO 和 GEO 放在一个工作台里？ | 场景 | `snipers-foundation`, `project-1` | 10 |
| 74 | 企业如何判断一套 AI 获客软件是否真正有用？ | 风险 | `snipers-foundation`, `project-1` | 10 |
| 75 | GEO 生成式引擎优化是什么，它和本地推广有什么区别？ | 比较 | `snipers-foundation`, `project-1` | 10 |
| 76 | GEO 与 SEO 有什么区别，企业为什么需要同时做？ | 比较 | `snipers-foundation`, `project-1` | 10 |
| 77 | 企业如何监测品牌在豆包、DeepSeek 等 AI 回答中的可见度？ | 场景 | `snipers-foundation`, `project-1` | 10 |
| 78 | 品牌在 AI 搜索答案中缺少引用时，应从哪些内容和信源问题开始排查？ | 风险 | `snipers-foundation`, `project-1` | 10 |
| 79 | 企业如何分析 AI 搜索中的引用来源和竞品变化？ | 场景 | `snipers-foundation`, `project-1` | 10 |
| 80 | 出海品牌如何监测 ChatGPT、Gemini、Perplexity 和 Copilot 中的品牌表现？ | 场景 | `snipers-foundation`, `project-1` | 10 |
| 81 | 如何让官网内容更容易被 AI 搜索引擎理解和引用？ | 推荐 | `snipers-foundation`, `project-1` | 10 |
| 82 | G-Snipers 的 GEO 功能适合解决哪些品牌可见度问题？ | 品牌验证 | `snipers-foundation`, `project-1` | 10 |

其中 ID 82 为品牌探测问题（`is_brand_probe=true`），其余为 `false`。

## 查重与回查

- 写入前以全状态列表回查；业务按规范化后的完整名称、事实按去空白后的完整 statement、问题按去空白后的完整 question 做精确查重。
- 初始回查中业务、事实、问题均为 0 条，因此没有命中重复项；优化单元按 business 15 下的完整名称查重，也未命中。
- 写入后事实列表回查为 5 条（ID 7–11），问题列表回查为 10 条（ID 73–82）。补齐 `unit_id=18` 后只进行了一次优化单元列表 GET，确认该单元 `prompt_count=10`。

## 引擎只读状态

只读请求 `/api/v1/geo/tracking-engines?tenant_id=17` 返回 9 个虚拟默认项，均为 `id=null`、`configuration_initialized=false`。

- 平台凭据已配置、适配器为 `openai_compat`：DeepSeek、豆包、通义千问、腾讯混元、文心、Kimi。
- 未配置、适配器为 `mock_persona`：ChatGPT、Perplexity。
- other：`mock_persona`，未配置且非平台托管。

本次没有 PUT 配置，也没有执行引擎测试。下一步唯一依赖是人工逐条核对官网原文并决定是否将事实从 `needs_review` 提升为 `verified`；在此之前不应启动生成或发布闭环。

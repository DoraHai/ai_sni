# GEO 内容工作台 Vue 化 · 方案 B

> 日期：2026-08-05  
> 策略：**按页迁移**静态工作台进主站 SPA，母稿 editor 最后迁。

## 已迁入 Vue（本 PR）

| 页面 | 路由 | 原静态页 |
| --- | --- | --- |
| 工作台枢纽 | `/geo/workbench` | geo-demo / dashboard 入口 |
| 内容任务 | `/geo/tasks` | articles.html |
| 混合编辑壳 | `/geo/tasks/:id` | iframe → editor.html |
| 机会词 | `/geo/prompts` | prompts.html |
| 事实库 | `/geo/facts` | sources.html |
| 跟踪引擎 | `/geo/engines` | engines.html |
| AI 配置 | `/geo/ai-settings` | ai-settings.html |
| 发布渠道 | `/geo/publishing` | publishing-channels.html |

观测侧（overview / visibility / citations / competitors / evaluation / deliverables）此前已 Vue。

## 母稿编辑器

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| **第一刀（已实现）** | ✅ `/geo/tasks/:id` | Brief / 事实 / 生成 / 保存 / check+Score / AI 审稿 / 规则补丁 |
| **第二刀（已实现）** | ✅ 同上 | 渠道勾选生成 / 页签编辑 / 导出 / 审校 / 回填 URL / Webhook 推送 |
| 静态完整页 | 兼容兜底 | 工具栏「静态完整 editor」 |

## 导航

主站侧栏 **GEO 增长** 下增加工作台相关项；概览快捷入口已指向 Vue 页。

## 后续

1. 渠道账号在 editor 内联创建/测试推送结果展示  
2. 静态页仅作兼容深链，最终下线  

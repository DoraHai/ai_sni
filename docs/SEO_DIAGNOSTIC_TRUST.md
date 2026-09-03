# 站内诊断依据与索引意图复核

## 来源与行为

- HTTP、robots/noindex 等是程序存档事实，不是实时状态；整改参考、TDK 生成是规则，可人工编辑，本功能不调用 AI。
- 页面是否希望参与搜索由人工确认，不能凭隐私页等名称猜测。技术设置符合意图不等于已收录或移除。
- Robots 禁止抓取不能证明 noindex；AI crawler / llms.txt 不作为传统搜索索引结论。
- 失败/未检测页面不评分，不进入平均值。统计只涵盖已纳管页面，最近检测时间只代表最近一页。
- 确认事件追加保存原因、真实用户、时区时间与当时检测证据；复检不清空意图。行锁和 expected_review_id 防止覆盖并发修改（409）。
- 路由继承 SEO 订阅门禁，显式验证 seo.site 权限和客户/网站/页面。不修改 TDK、官网、发布状态，不触发抓取。

## 验证

- SEO Python 回归；Vue 交互：`node frontend/scripts/test-seo-diagnostics.mjs`。
- frontend 内：`npm run build:seo`、`npm run verify:seo-build`、`npm audit --audit-level=high`。
- 独立 PostgreSQL 测试库尚未配置，迁移、真实落库和并发锁需另行验证；模拟会话测试不能代替真实数据库验收。
- 线上后续验收：404/超时不评分；noindex 默认待确认；保存后刷新/重新进入历史仍在；异站不可见；过期编辑409；未调用AI/发布/修改官网。

## 发布边界

开发基线 main 08a7122，SEO 生产基线 39deee2。生产拥有 main 尚未包含的站内问题中心、断链来源等功能，禁止整包用此开发分支替换生产；须独立生产同步 PR 保留已有功能并重新回归。

0085_seo_page_index_reviews 在 main 上父节点为 0080_seo_content_review_history。生产链已至 0084_seo_crawl_queued_status，后续需独立审查迁移图合流、前置迁移及 health/CI 版本，不得覆盖历史或隐藏改父节点。

## 生产候选（2026-09-03）

开发 PR #222 已合入 main（1f230903）。本候选基于 SEO 生产 39deee2 独立适配，保留原有问题中心、断链来源、异步抓取及失败处理，不引入 main 的 SEM/GEO CI 改动。

新增无操作合流节点 0086_seo_index_review_merge，父节点为 (0084, 0085)，原有迁移文件不变。
从线上 0084 到候选 head 的执行计划仅为：0085 新建索引意图表 → 0086 合流。

只读核查：线上服务 active/running，后端和前端均为 20260903T012613Z-39deee2e1f3c，schema=0084 且 health 正常。
开发 PR 的 CI 独立 PostgreSQL 迁移验证已通过；生产合流需由候选 PR 的迁移门禁再次验证。

本候选尚未应用到生产，migration=not-run。生产数据库迁移需另行审核授权，不能混入普通应用发布。
当前旧版健康检查严格要求 0084，数据库迁移后到新应用切换前会报告版本不匹配；迁移及受控发布应在同一确认的维护窗口执行。
如失败，不能仅回滚应用并声称恢复完成：必须检查数据库版本、确认新表是否已有记录，并走独立审核的数据库恢复方案，禁止盲目 downgrade 丢失确认历史。

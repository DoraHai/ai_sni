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

本轮 migration=not-run；未推送、合并、部署。生产数据库迁移需另行审核授权，不能混入普通应用发布。

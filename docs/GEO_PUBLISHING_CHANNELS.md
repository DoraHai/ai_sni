# GEO 发布渠道配置（Phase 1）

执行 `alembic upgrade head` 后，GEO 会新增发布渠道和渠道账号两类配置。

首次请求 `GET /api/v1/geo/publishing-channels?tenant_id=<tenant_id>` 时，系统为该租户初始化：官网、帮助中心/文档、公众号、知乎、百家号、头条号和行业媒体/垂直社区。

- 官网、帮助中心/文档：`auto_publish`，为后续 CMS / Webhook 连接器预留。
- 公众号、知乎、百家号：`draft_then_manual`，系统生成适配稿，运营审核后发布并回填 URL。
- 头条号、行业媒体/垂直社区：`manual_only`。

渠道账号的凭证以 JSON 请求体提交，服务端加密保存。读取账号列表时仅返回 `has_credentials`，不返回凭证原文。

本阶段不调用第三方发布接口；后续发布连接器只允许使用已启用渠道、已配置账号、已通过内容审校和质量门禁的渠道稿。

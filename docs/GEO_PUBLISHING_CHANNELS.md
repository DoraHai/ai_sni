# GEO 发布渠道配置

执行 `alembic upgrade head` 后，GEO 会新增发布渠道和渠道账号两类配置。

首次请求 `GET /api/v1/geo/publishing-channels?tenant_id=<tenant_id>` 时，系统为该租户初始化：官网、帮助中心/文档、公众号、知乎、百家号、头条号和行业媒体/垂直社区。

- 官网、帮助中心/文档：`auto_publish`；**Phase 2** 支持 Webhook 人工触发推送（见 `docs/GEO_PUBLISHING_CONNECTOR_PHASE2.md`）。
- 公众号、知乎、百家号：`draft_then_manual`，系统生成适配稿，运营审核后发布并回填 URL。
- 头条号、行业媒体/垂直社区：`manual_only`。

渠道账号的凭证以 JSON 请求体提交，服务端加密保存。读取账号列表时仅返回 `has_credentials`，不返回凭证原文。

Phase 2 官网/文档 Webhook 示例凭证：

```json
{"webhook_url":"https://cms.example.com/hooks/geo","method":"POST","headers":{},"secret":"optional"}
```

推送入口：`POST /api/v1/geo/content-tasks/{id}/push`（须审校通过、质量门禁、渠道稿已导出）。其他渠道仍走人工回填。

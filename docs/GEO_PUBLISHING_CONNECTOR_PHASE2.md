# GEO 发布连接器 Phase 2（官网/文档 Webhook）

> 状态：可合并 · 分支 `cursor/geo-publish-phase2-21de`  
> 前置：Phase 1 渠道账号登记 + 审校门禁 + 渠道稿导出

## 目标

对人触发的 **官网 / 文档** `auto_publish` 渠道，用已加密的 Webhook 凭证推送已导出渠道稿；成功时可写回 `GeoPublication`。

## 非目标

- 公众号 / 知乎 / 百家号 OAuth 或官方 API
- 无人值守定时推送
- WordPress/GitHub 专用适配器（通用 Webhook 即可）
- 新表 / 推送历史台账

## 凭证

`auth_type=webhook`，JSON：

```json
{
  "webhook_url": "https://cms.example.com/hooks/geo-publish",
  "method": "POST",
  "headers": { "Authorization": "Bearer …" },
  "secret": "optional-hmac"
}
```

有 `secret` 时发送 `X-GEO-Signature: sha256=<hmac>`。

## API

`POST /content-tasks/{task_id}/push`

- 前置：变体 `exported|published` + `assert_can_publish` + 账号 website/docs · auto_publish · webhook
- `mode=draft|publish`；`create_publication` + URL（请求体或响应解析）时写回填

## UI

- 发布渠道配置：Webhook 凭证占位提示
- 分发平台：推送草稿 / 推送发布

## 验收

- [x] https webhook + mock 2xx 可解析 URL
- [x] http / 非法 method 被拒绝
- [x] 签名头在 secret 存在时发出
- [x] 无新 migration
- [x] pytest 覆盖连接器

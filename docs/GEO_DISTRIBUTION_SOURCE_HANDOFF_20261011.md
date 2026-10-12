# GEO 多号通来源适配交接

## 接口

`app.geo.distribution_sources.load_source(session, actor_user_id, tenant_id, scope_id, variant_id, platform)`
只从当前数据库读取来源，不接收客户端正文、摘要、审核标志或素材声明。

`app.geo.distribution_sources.authorize_scope(session, actor_user_id, tenant_id, scope_id)`
返回 `None` 或稳定原因码异常。中央服务在绑定查询、项目启动/暂停/结束、任务列表等
尚未读取正文的入口也应调用它。下发到多号通的项目 ID 固定使用 `geo-<scope_id>`。

`app.geo.distribution_sources.list_sources(session, actor_user_id, tenant_id, scope_id, platform)`
供 `GET /api/distribution/v1/sources` 使用。它先执行 `authorize_scope`，最多返回 50 个
项目范围内、当前门禁通过的最新渠道稿摘要：

```json
[{"variant_id": 91, "source_revision": "geo-a...", "title": "标题", "platform": "wechat-article"}]
```

列表不返回正文、事实卡或未审核内容。不就绪稿件跳过；身份、权限、服务、顾问分配和
项目范围错误会拒绝整个列表请求。

`app.geo.distribution_sources.load_asset(session, actor_user_id, tenant_id, scope_id,
variant_id, platform, asset_id)` 只返回清单中同一不可变图片的字节。它先重跑
`load_source` 的全部授权、审核和发布门禁，然后复核字节数、媒体类型与 SHA256。

返回固定结构：

```json
{
  "module": "geo",
  "tenant_id": 1,
  "scope_id": 10,
  "variant_id": 91,
  "source_revision": "geo-a90-v3-c91-r...-q...-h...",
  "content": {
    "version": "geo-a90-v3-c91-r...-q...-h...",
    "title": "数据库中的渠道稿标题",
    "body": "数据库中的渠道稿正文",
    "assets": [{
      "id": "geo-asset-101",
      "sha256": "64 位小写十六进制",
      "mediaType": "image/png",
      "bytes": 68
    }]
  }
}
```

`source_revision` 同时绑定母稿 ID/版本、渠道稿 ID/更新时间、人工审核时间、内容摘要及
按顺序排列的素材 ID/SHA256/类型/字节数。
中央分发服务应在任务创建、派发前和结果采用前重新调用，并与任务快照严格比较。
审核撤销会直接拒绝读取；重新审核会产生新的 revision。

## 当前能力

- `wechat-article`：支持数据库内最新、已人工审核且通过现有 GEO 发布门禁的公众号纯文章。
- `xiaohongshu-image`：支持最新已审核小红书渠道稿及 1–20 张有序不可变 PNG/JPEG。
  单张最大 20,000,000 字节，单稿总量最大 100,000,000 字节。
- 其他 platform：返回 `geo_distribution_platform_unsupported`。

每次读取都会重新核验实名账号、当前角色权限、客户归属、GEO 服务有效期、项目状态、
当前顾问分配、项目业务及问题绑定、最新母稿、最新渠道稿、事实/品牌/人工审核和现有发布门禁。
权限、服务、分配、范围、母稿、渠道稿或审核发生变化都会拒绝旧来源。

## 受控素材入口

- `GET /api/v1/geo/distribution-assets`：列出当前项目最新小红书渠道稿的有序素材清单。
- `GET /api/v1/geo/distribution-assets/{asset_id}/content`：在重新校验同一实名顾问、租户、
  项目和最新渠道稿后，返回图片字节，响应不缓存。
- `POST /api/v1/geo/distribution-assets`：实名当前顾问上传 multipart 字节，仅接受完整解码成功的
  单帧 PNG/JPEG。不接受本地路径、远程 URL 或服务端下载。
- `DELETE /api/v1/geo/distribution-assets/{asset_id}`：删除同一最新渠道稿内的素材。

两个入口都需要 `geo.assets=edit` 与 `geo.content=edit`，并核对当前项目顾问分配。任何增删都调用
GEO 原有 `invalidate_review`，因此修改后的图片只有在客户重新审核后才会出现在清单中。
字节保存在 `geo_channel_assets`，并同时绑定 tenant/task/article version/channel variant。
上传和 `load_asset` 都会完整解码图片；如果同进程将 Pillow
`ImageFile.LOAD_TRUNCATED_IMAGES` 设为 `True`，GEO 返回 503 `geo_distribution_image_decoder_unsafe`，
不会沿用其他模块的宽松解码设置。

GEO 现有任务分发页 `/geo/tasks/{task_id}/distribution` 已接入最小顾问可点击工作流：
可选择 PNG/JPEG、查看当前有序配图、删除已有图片；界面不提供客户审核绕过按钮。
素材变更后依旧必须返回原生客户审核流程重新提交。

正式迁移仍是后续独立交付项；迁移未上线前不能将配图流程表述为生产可用。

## 稳定失败码

- `geo_distribution_actor_unavailable`
- `geo_distribution_tenant_forbidden`
- `geo_distribution_permission_revoked`
- `geo_distribution_entitlement_unavailable`
- `geo_distribution_assignment_unavailable`
- `geo_distribution_scope_mismatch`
- `geo_distribution_source_not_found`
- `geo_distribution_platform_mismatch`
- `geo_distribution_variant_stale`
- `geo_distribution_master_stale`
- `geo_distribution_variant_unavailable`
- `geo_distribution_content_empty`
- `geo_distribution_source_invalid`
- `geo_distribution_publish_gate_blocked`
- `geo_distribution_assets_unavailable`
- `geo_distribution_asset_not_found`
- `geo_distribution_asset_manifest_invalid`
- `geo_distribution_asset_decode_failed`
- `geo_distribution_asset_type_unsupported`
- `geo_distribution_asset_too_large`
- `geo_distribution_asset_count_exceeded`
- `geo_distribution_asset_total_exceeded`
- `geo_distribution_image_decoder_unsafe`
- `geo_distribution_platform_unsupported`

## 集成边界

本适配器不注册共享 API、不创建分发任务、不保存客户端快照、不调用平台，
也不判断远端发布结果。中央服务负责持久化来源快照、三次重读比较、幂等、重试、取消及回包拒绝。

本分支只在每个测试的随机 PostgreSQL schema 中通过 SQLAlchemy 创建新表。没有生成或执行生产迁移；
合并发布前仍需在统一迁移链中分配正式 revision。迁移未上线前，现有 `wechat-article` 不查询新表、继续可用。

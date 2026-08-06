# 多媒自动推送（配置可用底部）

> 代码已就绪：开通渠道包 → 填凭证 → 任务导出稿 → 审校 → 单推/批推。

## 支持的媒体

| 类型 | 推送方式 | 凭证 |
| --- | --- | --- |
| website / docs | `auth_type=webhook` | `webhook_url` (https) + method/secret? |
| wechat / zhihu / baijiahao / toutiao | `auth_type=social_api` | `platform` + `api_url` + `access_token` |

## 配置步骤（运维）

1. 打开 `/geo/publishing`
2. 点 **「一键开启多媒 auto 包」**（`POST .../enable-multi-media-auto`）
3. 看 **多媒自动推送矩阵**：`config_ready=false` 的渠道去建账号并填凭证
4. 矩阵 `config_ready=true` 后，只差任务侧：生成对应渠道稿并 **导出** + **审校通过**

## 任务侧

1. 生成渠道稿（website/wechat/…）
2. 每个渠道 **导出**
3. 审校通过
4. 编辑器底部 **多媒自动推送**：勾选就绪渠道 → 推送勾选 / **一键推送全部就绪**

API：

- `GET /api/v1/geo/publishing-channels/auto-push-status?tenant_id=`
- `POST /api/v1/geo/publishing-channels/enable-multi-media-auto?tenant_id=`
- `GET /api/v1/geo/content-tasks/{id}/push-targets?tenant_id=`
- `POST /api/v1/geo/content-tasks/{id}/push` 单渠道
- `POST /api/v1/geo/content-tasks/{id}/push-batch` 多渠道（允许部分失败）

## 社交凭证示例

```json
{
  "platform": "wechat",
  "api_url": "https://your-gateway.example.com/wechat/draft/add",
  "access_token": "REPLACE_ME",
  "method": "POST"
}
```

`api_url` 可为官方 OpenAPI 或自建转发（推荐），须 **HTTPS**；token 在各平台开放平台申请。

## 开发说明

- 新租户默认种子已含 6 路 auto_publish（官网/文档/微信/知乎/百家号/头条）
- 老租户用「一键开启多媒 auto 包」补齐类型与模式，不覆盖已有凭证
- 批量推送串行执行，单路失败不影响其他路

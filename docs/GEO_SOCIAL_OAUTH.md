# GEO 社交 OAuth / 真发布

> 状态：2026-08-07 已合入代码  
> 在原有 **gateway 转发（api_url + access_token）** 之上，增加 **微信公众号原生 API** 与 **通用 OAuth2 授权码**。

## 三种提供商

| provider | 适用 | 凭证 | 发布行为 |
| --- | --- | --- | --- |
| **wechat_mp** | 微信公众号 | `app_id` + `app_secret` | 自动取 token → `draft/add`；`mode=publish` 再 `freepublish` |
| **oauth2** | 知乎/百家号/头条等开放平台 | client_id/secret + authorize/token/api/redirect | 浏览器授权 → 存 token → POST `api_url` |
| **gateway** | 自建转发 / 已有 token | `api_url` + `access_token` | 原 social_api 行为 |

`auth_type`：`social_api`（wechat_mp / gateway）或 `oauth2`。

## 配置路径（运营）

1. `/geo/publishing` → 一键开启多媒 auto 包  
2. 为 wechat/zhihu/… 渠道 **新建账号**  
3. 选择提供商：
   - 公众号优先 **wechat_mp**
   - 其他平台用 **oauth2** 或 **gateway**  
4. wechat_mp：填 app_id/secret → **校验**  
5. oauth2：填客户端与回调 → **去授权** → 回站后再推送  
6. 任务：生成渠道稿 → 导出 → 审校 → 推送  

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/oauth/social/start?tenant_id=&account_id=` | 返回 `authorize_url` |
| GET | `/oauth/social/callback?code=&state=` | **公开回调**（HMAC state，无需 API Key） |
| POST | `/oauth/social/refresh?tenant_id=&account_id=` | 刷新 access_token |
| POST | `/channel-accounts/{id}/verify-social?tenant_id=` | 探测凭证（微信取 token / OAuth 是否已授） |
| POST | `/content-tasks/{id}/push` | 单渠道推送（自动刷新 token 并写回凭证） |

## 微信公众号说明

- 使用官方 `client_credential` 取 token（服务端，不是用户扫码网页授权）  
- 草稿箱接口：`cgi-bin/draft/add`  
- 可选群发：`cgi-bin/freepublish/submit`（推送 mode=`publish`）  
- **封面 thumb**：凭证可带  
  - `thumb_media_id`（已上传素材 ID）  
  - 或 `cover_image_url`（HTTPS 图，系统下载后 `material/add_material?type=thumb`）  
  - 或 `cover_image_base64`  
  上传成功后会回写 `thumb_media_id` 避免重复传  
- **本地演练**：`GEO_WECHAT_MP_MOCK=1` 或 `app_id` 以 `mock_` 开头 → 不访问微信  

## 知乎 / 百家号 / 头条 payload

gateway / oauth2 推送时 body 含平台约定字段（便于自建转发 1:1 映射）：

| 平台 | 主要字段 |
| --- | --- |
| zhihu | `zhihu.title/content/content_html/excerpt` |
| baijiahao | `article.title(≤40)/content/is_original/abstract/cover_images` |
| toutiao | `data.title/content/abstract/cover_images` |

## 可用性验收（无真实密钥）

```bash
# 进程内 mock + API（需 8011）
python scripts/accept_geo_social_usability.py http://127.0.0.1:8011 geo-demo-local-key 1
```

`GET /api/v1/geo/content-health` 的 `schema` 可检查 0054 迁移是否已执行。

## OAuth2 回调 URL 示例

```text
https://<你的 GEO API 域名>/api/v1/geo/oauth/social/callback
```

本地：

```text
http://127.0.0.1:8011/api/v1/geo/oauth/social/callback
```

须与平台控制台登记的 redirect_uri **完全一致**。

## 安全

- 凭证 AES 加密落库（与 webhook 相同主密钥）  
- OAuth `state` 用 JWT_SECRET/API_KEY 派生 HMAC 签名  
- gateway / wechat 外呼仍走公网 URL SSRF 防护  
- 生产请使用真实 app 凭证；勿把 secret 写进前端仓库  

## 与「完整 OAuth」边界

| 已做 | 未做（各平台差异大，后置） |
| --- | --- |
| 微信服务号 token + 草稿真接口 | 知乎/百家号官方字段的 1:1 协议（用 oauth2+api_url 适配） |
| 通用授权码 / refresh | 平台专属 scope 向导 |
| 推送前自动刷 token | 素材库上传封面图等扩展字段 |

---

关联：`docs/GEO_MULTI_MEDIA_PUSH.md`、发布页 `/geo/publishing`

# 公众号浏览器渠道来源映射修复

日期：2026-10-12。独立本地基线 `139cc7f57650afb1e83930149b6fac33cb9f861a`；原冻结工作树保持只读。本批生产代码仅修改 `app/seo_distribution_sources.py`，不涉及中央、SEM、GEO、共享认证、DTO 或数据库结构。

## 问题与修复

原生目录已经区分两条公众号通路：`wechat_browser` 是 `assisted`，不需要 AppID/AppSecret；`wechat_official` 是官方 API 通路，创建连接须有官方授权信息。之前来源适配器把中央 `wechat-article` 只映射为 `wechat_official`，导致正常浏览器渠道稿无法被中央读取。

当前映射：

| 中央平台 | 允许的原生平台代码 |
| --- | --- |
| `wechat-article` | `wechat_official`、`wechat_browser` |
| `xiaohongshu-image` | `xiaohongshu`（保持原有素材门禁） |

`load_source`、`list_sources`、`list_intake_candidates`、`load_intake_candidate` 使用相同白名单。连接 ID 仍来自所选稿件，且连接与稿件的原生平台代码必须完全相同：`wechat_browser` 稿件不能借用 `wechat_official` 连接，反向亦然。最新版本仍按每个母稿、每个连接独立判断；一条通路出现更新/生成中的稿件不会取代另一连接的合法稿件。其他原生平台和未知中央平台继续拒绝。

本批没有增加凭据，没有绕过官方连接创建校验，没有放宽来源连接启用/连接状态、实名用户、角色权限、顾问分配、客户/站点、服务有效性、人工审核、客户确认、版本、关键词或素材门禁。`ready` 元数据仍不等于发布授权。来源适配器继续只读，不 flush/commit，不发起平台网络请求。

## 验证方式

新增 `tests/test_seo_browser_channel_sources_postgres.py` 使用 SEO 自有回环 PostgreSQL 随机 schema、合成客户/稿件、真实 JWT 与 ASGI 请求：

- 调用**既有原生连接创建接口**：`wechat_browser` 不传 credentials 创建成功，数据库 `credentials_encrypted IS NULL / has_credentials=false`；同样不传凭据的 `wechat_official` 请求返回 400。
- 浏览器渠道的已审、已确认稿通过来源读取、就绪列表、候选列表和点查，source_revision 一致；匿名请求拒绝，顾问分配撤销后同一 JWT 拒绝。
- 覆盖 pending、母稿未审、未确认、母稿/渠道稿过期、实名身份/角色/分配/租户/站点/服务撤销、停用连接及未连接 API 模式。
- 覆盖两种公众号代码互串、与小红书互串、未注册代码和不支持的其他渠道。
- 两个独立连接共用母稿时分别读取、分页及保留自己的 latest；浏览器连接的新稿仍在生成时，不暴露其旧稿，也不隐藏官方连接的合法稿件。
- 同 ID 审核前后 draft_version 稳定，数据库缺结构保持 503，不伪装成无记录或待适配。

既有官方通路、图文素材、候选接口、国内目录和发布逻辑测试单独回归。官方连接 `connected` 的测试行只是来源状态门禁的合成夹具，不代表验证了官方账号或真实 API 授权。

准确测试数、报告哈希、代码提交、文件哈希见 `SEO_BROWSER_CHANNEL_ACCEPTANCE_EVIDENCE.json`。没有使用中央 55463 / GEO 55527 数据库；没有启动共享服务或修改生产数据。

## 给中央验收的接线说明

将原生源码根目录切换到本工作树的冻结版本。验收 UI 对 MHT 浏览器公众号通路创建 `wechat_browser` 原生连接，并让对应渠道稿保留相同平台代码和连接 ID；中央平台仍传 `wechat-article`。不要为浏览器通路创建官方 API 连接或填写假密钥。

本批已验证的是浏览器**渠道模式**和原生来源接口，不是真实浏览器登录、MHT 实际发稿或微信平台发布。中央 UI 接线后的独立验收仍由中央继续，本批未推送、部署或执行生产 DDL，SEM 保持不动。

# SEO 原生小红书图文素材交付（本地候选）

## 现有存储与实现选择

`seo_distribution_package.py` 仅临时下载正文配图生成 ZIP，没有持久的审核绑定或完整资产摘要。
`SeoPageCapture` 是页面检查截图，不是顾问审核过的分发图片。此次均不混用。

新增 `seo_distribution_media_sets` / `seo_distribution_media_bytes` / `seo_distribution_media_reviews` 三张独立表。
第一期直接保存规范化图片 bytea，避免引入可变路径、外部 URL、运行时下载或跨租户公共文件目录。
三张表有禁止 UPDATE/DELETE 的触发器，素材集保存历史而非覆盖，关联外键均 RESTRICT。
数据库特权操作者仍可绕开触发器，因此下载再次计算 SHA256，不能把触发器当绝对防篡改能力。

DDL 为 `scripts/seo_distribution_media_schema.sql`，仅在随机 schema 的专用本地测试库验证。
**尚未分配 Alembic revision、未注册迁移、未在生产执行**。上线前需数据库负责人审核迁移和存储容量/保留策略。
此版本不提供资产清理；没有把历史不可变数据当作无限存储承诺。

## 上传与独立审核

路由独立位于 `app/api/seo_distribution_media.py`，本地集成应用显式 include_router。
没有改 main / seo_main 或生产路由注册。独立候选 UI 已补齐，未改共享工作台文件。
挂载此 router 后，同源入口为 `/api/seo/distribution-media/workspace?tenant_id=<客户>&site_id=<网站>`。
页面读取同源 SEO 现有登录会话（复用 sessionStorage.js），不接收 URL 中的 token，不提供手工粘贴凭证入口。
静态壳不含业务数据；稿件、图片和所有动作均重新经过实名 API 鉴权。
打包时需包含 `app/static/seo-distribution-media/` 及现有 `frontend/src/store/sessionStorage.js`。
生产导航接入和路由挂载仍需中央集成，不能因为候选页面完成而声明线上已开放。

| 请求 | 用途 |
| --- | --- |
| GET `/api/seo/distribution-media/variants?tenant_id=4&site_id=2` | 顾问编辑选择器，最多 50 条最新渠道稿，允许待审；与只列已审来源的分发列表严格分开 |
| GET `/api/seo/distribution-media/variants/{variant_id}?tenant_id=4&site_id=2` | 读取当前正文、status、edit_token、set_id 和图片摘要 |
| POST `/api/seo/distribution-media/variants/{variant_id}/assets` | multipart：tenant_id、site_id、expected_token、按显示顺序排列的 files，整体替换图片集 |
| GET `/api/seo/distribution-media/variants/{variant_id}/assets/{asset_id}?tenant_id=4&site_id=2` | 授权顾问审核前查看最新素材字节；不是设备分发出口 |
| POST `/api/seo/distribution-media/variants/{variant_id}/review` | JSON：tenant_id、site_id、set_id、expected_token，审核当前正文与图片并冻结 |

ID 仅为合成测试示例。所有入口使用真实实名 JWT 和当前 DB 用户/角色/租户/模块有效期/站点状态/服务暂停/顾问分配检查。
API Key 无 user_id 不可替代实名账号。上传者或渠道稿 created_by 不能自审，审核者需另一个同范围有效顾问。
资料母稿既有审核与客户确认门禁仍需通过，冻结失败整笔事务回滚，不残留半完成审核。

图片限制：每集 1–9 张，仅 PNG/JPEG 单帧，每张输入与规范化输出均不超过 **20,000,000 bytes**（严格 v1 十进制上限），
合计均不超过 40,000,000 bytes，每张最多 **2500 万像素**。请求体在 multipart 解析前有总量限制。
Pillow 完整 verify/load 后按像素重新编码、处理 EXIF 朝向并去掉元数据/尾随负载，MIME 不信任文件名或客户端声明。
规范化在工作线程执行。顾问预览与审核的是这些存储字节，不是未经清理的原始文件。
上传、审核冻结、顾问图片预览与 load_asset 均检查 ImageFile.LOAD_TRUNCATED_IMAGES。
宽松截断模式开启时失败关闭，返回脱敏 503；不修改任何 Pillow 进程全局设置。
字节读取除摘要校验外再次完整 verify/load，并在解码前后检查该开关，截断 JPEG 不因其他模块设置而混入审核。

上传操作锁定渠道稿，用 edit_token 校验预览未过期，然后提升 revision_number、清空 reviewed_by/reviewed_at 并设为 draft。
并发同 token 上传仅一个提交。素材集绑定正文、来源版本和渠道修订；正文后来变更须重新上传核对，不能沿用旧冻结记录。
审核冻结保存精确渠道稿状态、审核身份/时间及更新时间的 seal。既有审核接口单独给稿件设 approved 不能绕过素材冻结。
已冻结记录不重写，撤审再审须新建素材集；该限制用来保留审核历史。

## 分发来源契约

`load_source` 与 `list_sources` 现支持 `xiaohongshu-image`，仍复用所有母稿/渠道稿最新版本、人工审核、
客户确认、关键词、平台和权限校验。素材元数据在同一来源 SQL 快照读取。
小红书正文保持已审文本/HTML，禁止内嵌图片 URL 等外部资源；图片通过独立 assets 顺序交付。

```
assets = [{"id":"<server UUID>","sha256":"<64 hex>","mediaType":"image/png","bytes":1234}, ...]
```

按序 manifest 同时进入 source_revision 指纹和中央 content_digest，换图、调序或重新审核均使旧授权失效。
公众号 `wechat-article` 继续返回 assets=[]，不查询新增素材表；来源字段格式保持兼容。

新增 `async load_asset(db, actor_id, tenant_id, scope_id, variant_id, platform, asset_id) -> bytes`：
先读取当前已审来源，只接受其 manifest 中的 asset_id，按真实客户/网站/稿件关联取 DB 字节，
核对长度/摘要后再次重验完整来源。未知 ID/路径/URL、其他稿件素材、历史替换素材均拒绝。
读取只读、不提交、不触发下载或外部发布；调用方仍需短 READ COMMITTED 事务和任务级授权检查。

新失败码：422 `seo_distribution_asset_invalid`（格式或限额）；403 `seo_distribution_independent_review_required`；
404 `seo_distribution_asset_not_found`；409 `source_stale/review_required/assets_unavailable` 均带 seo_distribution_ 前缀；
缺表或 DB 不可用为脱敏 503。路由响应禁缓存，图片带 nosniff。

## 验证与边界

原生测试：`tests/test_seo_distribution_media_postgres.py`。
覆盖完整 PNG/JPEG 解码、错误格式、超大/多帧、元数据清理、数量/合计限额、独立审核、只读读取、
SHA256、顺序、并发替换、回滚、旧 ID/任意路径拒绝、权限撤销、旧正文/旧审核/新草稿拦截、存储损坏拒绝。
真实 JWT HTTP 测试覆盖上传→图片预览→拒绝自审→另一顾问冻结。
`tests/test_seo_distribution_media_browser.py` 用真实 Chromium、实名 JWT、原生数据库验证候选页面：
读取可编辑稿件→上传 PNG/JPEG→显示全部图片→自审拒绝→另一顾问审核→换图撤审→切换范围清除旧预览。
页面错误和站外请求均为 0，截图/证据保存到 TEMP `seo-media-browser-approved.png` / `seo-media-browser-evidence.json`。
通过 `SEO_MEDIA_BROWSER_TEST=true` 显式启用该本地浏览器测试。

与中央最新原生 router/broker 联调：上传冻结→小红书来源列表/预览→设备绑定/start→handoff/exchange→
设备端点逐张读取 PNG/JPEG 并核验 SHA256；换图、撤审或取消顾问分配后设备下载拒绝，旧 grants 不再下发。
受测中央文件 hash 记录在 `SEO_DISTRIBUTION_BROKER_EVIDENCE.json`，不以其未提交工作区 HEAD 替代真实版本。

本批未推送、部署、生产建表、真实平台登录或发布；独立上传审核 UI 已本地验收，
共享工作台导航/生产路由集成和真实平台上传仍待中央/设备侧验收。

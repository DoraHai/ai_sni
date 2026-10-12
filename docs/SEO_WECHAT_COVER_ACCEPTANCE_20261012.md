# 原生公众号封面审核链（本地候选）

基线 `b4d8387123355348f79e26ea2838585c5106a4b9`，独立分支 `codex/seo-wechat-cover-acceptance-20261012`。只改 SEO 媒体/来源适配器及其独立 API、测试和本文档；未改共享 auth/models/core、main、SEM/GEO、旧临时客户端或云环境。原生基线没有 AGENTS.md/CLAUDE.md，已按现行中央 AGENTS 和原生 HANDOVER/素材说明执行本次限定范围。

## 行为与授权边界

`wechat_browser`、`wechat_official` 都映射中央 `wechat-article`，但 variant 与 connection 的原生 platform_code 必须完全相等，不能借另一个别名的连接。媒体编辑器只读取本范围、启用连接、当前母稿版本和同母稿/连接的最新 article 渠道稿。

微信最多且只允许上传 **1 张** PNG/JPEG；该唯一首资产是封面，不插入或改写正文。小红书继续为按序 1–9 张图文。其他渠道没有新增素材能力。限额及解码沿用原实现：单张最多 20,000,000 字节、总量 40,000,000 字节、单帧、最多 2500 万像素；完整 verify/load、EXIF 朝向、按像素重新编码、去元数据与尾随负载。宽松 Pillow 截断开关开启则失败关闭，不更改进程全局解码设置。

`replace_assets` 使用当前 edit_token、锁渠道稿并上传规范化字节，渠道 revision_number++、status=draft、清空审核记录。母稿正文/version/客户确认不被这个动作改写。`review_assets` 必须由当前有内容/网站编辑权限且当前分配到网站的另一个实名顾问完成；本次上传者和 variant 创建者不能自审。超管身份也不自动免除网站顾问分配。所有原母稿人工审核、准确版本客户确认、平台正文/关键词/最新版本门禁仍由真实 load_source 执行，失败整个审核事务回滚。

审核封存 manifest、不可变字节和 variant seal；source_revision 对微信封面显式包含精确按序 manifest、素材集 ID、reviewer、review 时间及 seal，并通过内容 version/manifest进入中央 v1 content_digest。封面更换、正文/母稿变更、撤审后单独旧接口再批准、确认撤销或失权不能继续使用旧 source。intake draft_version 包含当前素材集内容；上传/换封面改变它，单纯从待审核到批准保持同一 draft_version，避免重复意图。

## 源接口

```python
async load_source(session, actor_user_id, tenant_id, scope_id, variant_id, platform) -> dict
async load_publication_source(session, actor_user_id, tenant_id, scope_id, variant_id, platform) -> dict
async load_asset(session, actor_user_id, tenant_id, scope_id, variant_id, platform, asset_id) -> bytes
```

原 load_source 没有 action，继续兼容无封面纯文本 preflight/handoff：assets=[]。新增 load_publication_source 调用完整真实 load_source，并对公众号要求恰好 1 个当前已审封面，否则 `409 seo_distribution_cover_required`；它自己不派发、不签 grant、不提交、不调用平台。中央正式 publish wrapper/执行端需使用该窄门禁，不能仅调用旧 load_source 就称已具备发布封面。小红书原有素材语义保持。

三张可选表全部缺失时公众号纯文本仍可读；只建了一部分则503，不能把不完整存储解释为无封面；全部存在时读取当前素材集，即使有图但未审也不能忽略它。新建空表不改变已有纯文本 source_revision 或 intake draft_version。不检查/读取其他 schema 的媒体表，也不安装表或假 stamp。

load_asset 只接受当前完全通过原生权限/审核/版本门禁的 manifest ID，通过真实 variant/tenant/site关联读取数据库字节，核对 SHA256/长度并严格完整解码，最后再次重验同一来源。路径、任意 URL、其他网站/客户/稿件或历史被替换的资产不允许；不下载、不接浏览器 cookies，不把页面截图当封面。

## 真实原生 API 与挂载

仍使用 `app.api.seo_distribution_media.router`，前缀 `/api/seo/distribution-media`。此批未修改任何生产路由注册，中央独立验收 factory 需要显式挂载该 router 或以下确切 endpoint：

| endpoint 名 | 请求 |
|---|---|
| `drafts` | GET `/variants?tenant_id=15&site_id=6` |
| `preview` | GET `/variants/2?tenant_id=15&site_id=6` |
| `upload` | POST `/variants/2/assets`，multipart tenant_id/site_id/expected_token/files（一张实际 PNG/JPEG） |
| `preview_asset` | GET `/variants/2/assets/{server_asset_id}?tenant_id=15&site_id=6` |
| `review` | POST `/variants/2/review`，JSON tenant_id/site_id/set_id/expected_token |

这里 15/6/2 仅说明后续已授权独立验收对象，不是本地测试中的实际写入。上传100007、审核100008之前需确认两人当前原生网站分配与权限；不向上传者授予自审批准。preview 新增 `platform`、`max_images`、`asset_role`（微信分别 wechat-article/1/cover），原 title/body/edit_token/set_id/assets 保留。source 的 assets 契约仍严格是 id/sha256/mediaType/bytes 四字段，未塞额外角色字段。静态候选素材 UI 没有本批实页验证，根验收用实际 API；共享工作台导航/UI未改。

## DDL 冻结与 namespace

复用原 b4 已有 `scripts/seo_distribution_media_schema.sql`，**字节内容未改、没有新增迁移**：

- Git blob：`89fbe1768453643b9c5f2a098f7d6508f8ba25b2`
- Git/LF blob SHA256：`5e2f95f87a9a3df19144b57b24e2e6b7c67c900eaa02e3272274c362b0f923a8`
- 本 Windows raw/CRLF SHA256：`eb3d049be8b43d8f7987a5cca38f07e78af53fb055688188af9b5ab9e40c60e0`

SQL 无显式 schema，须在经过审核的单一事务中明确 search_path，再核 current_schema；不能依靠默认 public。完整对象只有：

- 表 `seo_distribution_media_sets`、`seo_distribution_media_bytes`、`seo_distribution_media_reviews`。
- 索引 `seo_distribution_media_latest`；各表原 PK/unique/check/FK。
- 函数 `seo_distribution_media_immutable`。
- 三个不可变触发器 `seo_media_sets_immutable` / `seo_media_bytes_immutable` / `seo_media_reviews_immutable`。
- FK仅引用同 namespace 的既有 tenants/users/seo_sites/seo_distribution_variants 及上述素材表，RESTRICT；不修改原表或原稿。

本地仅自己的 loopback **55567** / `seo_workflow_test` 随机 `seo_workflow_test_<32hex>` schema 执行该 SQL并验证。不存在 cloud/production DDL或迁移执行声明。根后续如决定在独立云验收库安装，须单独确认 acceptance_seo/current_database/角色/原对象及 public 三表状态；执行前后核 SQL 原始SHA、全对象列表与作用域。不能在已有部分表上盲目重跑此非幂等建表 SQL。

## 验证与剩余工作

新增 `tests/test_seo_wechat_cover_postgres.py`：**14 passed**。使用实际本地 PostgreSQL、真实原生模型/角色/分配/客户确认、原生素材写入器和 JWT；封面像素是程序生成的12×8合成图，不是实际客户图。覆盖PNG browser/JPEG official全链、纯文字无封面正式门禁、严格别名、1图数量、拒自审、换图/intake版本、当前母稿/确认/旧seal/创建者/范围/撤权/损坏字节、缺表及部分表、原生 JWT ASGI multipart/审核/撤权。没有 mock 鉴权、审核、来源或图片存储写入器。

相关旧四文件 source/media/intake/browserchannel 回归 **166 passed**，包括真实PG用例，也包含decoder unit和显式故障注入/契约用例；不能把整个166都称成未mock的真实业务流。新14与旧166是两次独立报告，不重复计数。ASGI HTTP不是TLS/真实浏览器/官方平台。首次收集因本地缺少docx而未启动测试，后使用既有离线python-docx/lxml依赖，只读引用，无网络安装。

按实际 testcase 对照测试函数 AST，旧166中 **161 项有真实 PostgreSQL fixture**（其中包含明确的故障注入/异常传播边界），**5 项是纯 decoder/catalog unit**。新14全部使用真实PG fixture。基线母稿审核/客户确认记录是隔离合成模型行 seed，封面上传/独立审核使用实际原生方法/HTTP；不宣称本轮实际调用过客户母稿确认 API 或真人客户审校。测试 schema 采用原生 ORM 表结构和原有 fixture 初始化，不冒称执行完整原生 Alembic 0105链。封面三表采用该冻结 SQL 的真实 DDL。测试数据库为 PostgreSQL16.15，所有随机测试 schema 回收后残留0。

XML在 TEMP `seo-wechat-cover-tests-20261012`：

- `cover-first.xml`：14/0 errors/0 failures，SHA `6c715d9b9bddcbb25524408249f27f83e1d9278d4f5deebd9c7b0c802c4ae182`。
- `native-regression.xml`：166/0 errors/0 failures，SHA `dea1ee55ee0ac960c96c7c4cc5e9eae1f27c4f91eddd13259c0827ff86cb9661`。

母稿61v2正文、原60/variant1、真实variant2均没有本批操作。旧TEMP驱动硬 pin / assets0 条件保持，不为新封面预先修改常量。根需复核此源码及SQL，更新独立native pin/挂载，完成100007实际上传→100008当前独立审核→真实source/assets读取并核字节→精确新source revision和digest；之后才更新本轮单任务permit/客户端冻结元数据。实际生成封面、微信上传/排版/最后提交、公开页/客户交付回传和暂停收口仍未验证，不声称已发布成功。

# SEO 中央分发来源适配器（本地候选）

基于冻结候选 `75dfa5e9fc75af51a27f4bc221ba3008ca7f1724`，独立目录
`D:/SNIPERS国内版/ai_sni-worktrees/seo-distribution-sources-20261011`，分支
`codex/seo-distribution-sources-20261011`。本次只新增来源模块、针对性测试和本文档。
没有修改原工作区、共享控制、生产 API 注册、UI、数据库或平台连接配置。

## 导出函数

```python
async authorize_scope(session, actor_user_id: int, tenant_id: int, scope_id: int) -> None
async load_source(session, actor_user_id: int, tenant_id: int,
                  scope_id: int, variant_id: int, platform: str) -> dict
async list_sources(session, actor_user_id: int, tenant_id: int,
                   scope_id: int, platform: str) -> list[dict]
async load_asset(db, actor_id: int, tenant_id: int, scope_id: int,
                 variant_id: int, platform: str, asset_id: str) -> bytes
```

导入位置 `app.seo_distribution_sources`。actor_user_id 必须来自中央服务已认证的实名主体，不能接受客户端冒充。
authorize_scope 从 DB 最新用户、角色、客户绑定、SEO 模块有效期、网站状态、服务暂停开关与有效顾问分配判断，
不读取稿件表。中央绑定查询、任务列表、项目启动/暂停/结束等接口先调用它，再访问范围内数据。
多号通 projectId 由中央服务固定组装为 `seo-<scope_id>`；不把客户端 projectId 当权限依据，不增加本接口返回字段。

load_source 先复用 authorize_scope，之后用一条原生 PostgreSQL SELECT 的同一 MVCC 快照读取
身份、范围、母稿、渠道稿、渠道连接、最新修订、最新客户确认和目标关键词；同时再次核验身份及范围。
只选择标量列，既不读取密码/加密凭证，也不使用 ORM identity map 中可能过时或被改写的正文。
内部禁用 autoflush，不提交、不加写锁、不迁移、不下载、不调用模型或平台。

调用方使用短 READ COMMITTED 事务，在任务创建、派发前、回包采用前分别重新调用并比较完整快照。
不要跨平台网络请求保持旧事务、缓存授权或使用 REPEATABLE READ 的历史快照；单次函数调用不是未来授权保证。
错误传播时由调用方回滚事务，不自动重试外部发布。

## 顾问可选稿件列表

中央 `GET /api/distribution/v1/sources` 可调用 list_sources；本模块不注册生产路由。
先 authorize_scope，再按真实客户/网站/平台读取最新 article 渠道稿 ID，
以 updated_at、id 倒序取最多 50 个 approved 候选。最新版本计算包含未审核稿，
因此有更新 draft/pending_review 时不会回退到旧 approved；每个候选仍须通过 load_source 完整门槛。
未就绪候选跳过，不再向后补满 50 条；这是候选上限，不是分页总数或全量统计。

返回只含 `{variant_id, source_revision, title, platform}`，不返回正文、事实、审核标志或未审内容。
例如 `[ {"variant_id":60,"source_revision":"seo-m3-v2-<64位SHA256>",
"title":"selection article","platform":"wechat-article"} ]`。
没有合格候选时返回 `[]`；小红书图文只列出带当前独立审核冻结素材集的稿件。
直接读取缺少素材或素材未审的稿件返回 `409 assets_unavailable/review_required`；素材表缺失返回 503。
身份、权限、范围、模块/网站不可用或数据库故障均拒绝整页，不转成空列表；返回前再次校验范围。
列表选择不替代创建/派发/采用回包时的 load_source 重验，沿用短 READ COMMITTED 事务要求。

## 来源门槛与结果

- variant_id 是现有 `SeoDistributionVariant.id`；不接客户端正文、摘要或审核布尔值。
- 客户、网站、母稿、渠道稿、渠道连接均需归属一致。渠道连接需启用；既有 API 模式还需 connected。
- 母稿须 article、ready/published，带实名人工审核记录。渠道稿须为同母稿/连接的最新修订，approved 且带人工审核记录。
  更新的 draft 也使旧 approved 稿失效，不能退回寻找旧已审版本。
- source_version 必须等于当前母稿 version_count；必须有最新的准确母稿版本/正文 hash 对应的 customer_direct
  或 advisor_proxy 确认。新拒绝、正文变化、旧版本确认、缺确认表都拒绝，**不使用旧发布接口的缺表兼容放行**。
- 保留既有平台标题/正文清理与目标关键词检查；需要再次清理的正文拒绝，避免悄悄更改已审内容。

```json
{
  "module": "seo",
  "tenant_id": 4,
  "scope_id": 2,
  "variant_id": 60,
  "source_revision": "seo-m3-v2-<64位SHA256>",
  "content": {
    "version": "seo-m3-v2-<相同SHA256>",
    "title": "selection article",
    "body": "<p>selection article body</p>",
    "assets": []
  }
}
```

上述 ID 为隔离测试合成对象，不是已授权生产资源。实际 revision 使用合法 ID 字符，包含母稿版本与渠道稿修订，
SHA256 覆盖范围/平台、母稿业务正文摘要、渠道稿正文与审核、最新确认身份/时间及关键词依据。
正文未升版本但变化、撤审后重新审核、确认变化也改变 revision；撤审或撤权直接拒绝旧任务。

平台映射：`wechat-article` → SEO `wechat_official`；`xiaohongshu-image` → SEO `xiaohongshu`。
首期仅公众号纯文章可返回 assets=[]。包含配图、视频、SVG、嵌入资源、CSS 图像或 Markdown 图像时拒绝。
现有离线材料包只临时下载图片，因此没有复用为已审资产。
小红书图文已追加原生上传、独立审核和数据库不可变字节存储，详见 `SEO_DISTRIBUTION_MEDIA.md`。
正文与图片分开保存，不从正文 URL 下载；按序 assets 的 id/sha256/mediaType/bytes 纳入 source_revision，
进而纳入中央 content_digest。load_asset 仅允许当前完全通过来源门禁的稿件关联资产，
读取前后重验来源，并核对实际字节的长度和 SHA256。公众号纯文章不依赖新增素材表。
公众号封面/图片上传和真实发送仍由中央分发与多号通侧另行核实，当前支持的是来源快照，不代表发布验收通过。

## 固定失败码

HTTPException.detail 始终是 {code,message}，code 前缀 `seo_distribution_`，消息为脱敏中文：

| HTTP | 原因码后缀 |
| --- | --- |
| 422 | invalid_scope、platform_unsupported |
| 403 | identity_required、advisor_required、independent_review_required |
| 404 | scope_not_found、source_not_found、asset_not_found |
| 409 | site_unavailable、platform_mismatch、connection_unavailable、content_type_unsupported、source_stale、review_required、confirmation_required、assets_unavailable、content_invalid、keywords_invalid |
| 503 | source_unavailable（结构缺失或 DB 不可用；不输出 SQL、DSN 或原异常） |

## 验证与未覆盖范围

`tests/test_seo_distribution_sources_postgres.py` 在专用 loopback `seo_workflow_test` 随机 schema 中运行。
覆盖只读事务、禁止外部 HTTP、缓存/未刷新的 ORM 修改不替换来源、真实 JWT + 当前数据库角色撤权、
独立范围校验不读正文、母稿/渠道稿版本和审核、确认撤销与缺表、关键词、平台不匹配与素材保留边界。
列表另覆盖只读事务、仅摘要、禁止旧已审稿回退、50 个候选上限、跨范围拒绝、撤权整页拒绝和结构缺失拒绝。
不覆盖生产数据、中央任务状态机、绑定账号、UI、多号通真实上传/发布及其回包。这些都不是本模块完成声明。
最新合跑报告保存 TEMP `seo-distribution-integrated-regression.xml`；中央固定版本、案例及文件校验值见
`SEO_DISTRIBUTION_BROKER_EVIDENCE.json`。初始三文件来源适配后已追加素材批次；应按提交及当前素材文档选取，
不需要合并整个冻结分支。

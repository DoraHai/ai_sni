# 独立验收入口：SEO 公众号封面整合

本批完成中央验收入口接线，尚未完成真实公众号发布。本地没有启动服务、访问平台、执行数据库 SQL、上传图片或改动真实稿件。总控负责独立云验收库安装、实际素材上传与独立审核，以及唯一单篇发布。

中央基线 `e275299c9a18bf19d4314f207f69fb86dc356b6e`；可运行代码冻结 `f20aa136ec263ce71e6c158b1d66c3806837096b`，tree `255850f2d14a863148564a2f9228b8f0270b249b`。实现只涉及三个验收脚本和两个测试文件。共享 core/auth/models、SEM、GEO 业务源码、gateway 六文件及旧 TEMP 单篇客户端/writer均未修改。总控后续 gateway 独立补丁由总控合并，本分支没有复制或回退它。

SEO 原生固定 `3087e62f23e799fe82d279f79f698f0499bf3a27`，GEO 保持 `46dacbd805afc00f37eba344306fde004039efed`。Linux release 激活固定新 SEO pin；通用 native factory 的审核白名单保留既有 b4 并增加新 pin，但缺少 `load_publication_source` 的旧运行来源不能通过正式发布 wrapper。未修改旧 Windows 初始化器的 b4 默认配置。

## 发布门禁

精确 POST `/api/distribution/v1/tasks` 的 publish 分支保持同一实际数据库会话，按原 device → scope → account advisory 锁顺序执行。锁后重新读取完整私有 permit，调用现有当前授权检查，再调用 `core.adapter('seo').load_publication_source(db, actor, tenant, scope, variant, platform)`。

原生函数重新检查当前范围、母稿审核/客户确认、渠道审核、连接平台与素材封存。验收 wrapper 只接受 module/tenant/scope/variant/source revision 全部匹配 permit 的结果，使用真实中央 `ApprovedContent` 严格契约和 `content_digest` 算法，并要求 assets 恰好一项、content.version 与 permit.source_revision 一致。缺函数返回安全 503；坏契约、错版本、错摘要或缺/多封面拒绝。原生 403/409/503 不转换为成功。

读取原生来源可能等待，因此在 native core.enqueue 前再次重读相同 permit、核请求及剩余时间。core.enqueue 的当前项目 running、owner、原生 load_source、binding、排期、幂等和双 grant 逻辑完全保留。提交前仍核对实际完整任务、同一 permit、两个不同 grant、lease 及期限均不越过 permit；任何异常或取消回滚整个外层事务。preflight/handoff、GET tasks 和 GEO 入口保持原行为。

上传封面会使当前 variant revision 增加并退回 draft，审核封存后 source revision/digest 必须更新。旧 permit/旧 source 不能继续使用。封面仅作为首资产，中央不把它插进正文；正文图像禁令、素材 URL/path 禁令以及原生范围检查保持。

## 原生 API 接线

仅 SEO 验收入口挂载实际 `app.api.seo_distribution_media` 中五个 APIRoute，保留 PrivateMediaRoute、Depends、当前 require_auth/get_session 与原生处理函数。必须五个路径和方法精确存在，缺项或方法变化时拒绝组装，不部分挂载。workspace/ui 静态入口未挂载。

前缀 `/api/seo/distribution-media`：

| handler | 方法与路径 | 本次操作字段 |
| --- | --- | --- |
| drafts | GET `/variants?tenant_id=15&site_id=6` | 真实当前顾问范围 |
| preview | GET `/variants/2?tenant_id=15&site_id=6` | 返回当前 edit_token/set_id/assets；微信 max_images=1、asset_role=cover |
| upload | POST `/variants/2/assets` | multipart tenant_id=15、site_id=6、expected_token=刚读 edit_token、files=一张实际 PNG/JPEG |
| preview_asset | GET `/variants/2/assets/{asset_id}?tenant_id=15&site_id=6` | asset_id 取本 variant 当前集，不能任意 URL/path |
| review | POST `/variants/2/review` | JSON tenant_id=15、site_id=6、set_id=刚读当前 UUID、expected_token=上传后重新读 edit_token |

原生 review 使用另一名当前有权限顾问，不能与 uploaded_by 或 variant.created_by 相同。按本轮目标，100007 上传，100008 独立审核；上传后重新预览并实际核正文/封面，再执行 review，不能复用上传前 token。review 成功返回真实原生 source，母稿61v2正文无需为封面重写，variant2 的版本/审核由真实接口推进。本批没有操作这些真实 ID。

顾问分配接口已有挂载，无需新增权限模型：

```http
GET /api/v1/seo/workbench/advisor-assignments?tenant_id=15&site_id=6
PUT /api/v1/seo/workbench/advisor-assignments
Content-Type: application/json

{"tenant_id":15,"site_id":6,"advisor_user_id":100008,"active":true}
```

PUT 必须使用当前实名管理员 JWT，并具有 seo.content edit 和 settings.accounts edit。原生 handler 校验当前 tenant/site、原生0105/0106结构、目标用户启用、目标 tenant 为 null 或15、目标角色 seo.content edit，再锁定并保存原生 SeoSiteAdvisorAssignment；没有直接 SQL 授权或替代 scope。GET 要求 seo.content edit 和 settings.accounts view。现有验收客户只读 middleware 保留，客户不能调用这些素材写入或分配接口；原生 handler 再检查当前身份与范围。

## 总控安装与运行顺序

以下是交接步骤，本批均未执行。只允许现有独立验收 `distribution_acceptance_seo` 数据库和 `acceptance_seo` namespace；不运行 initialize/bootstrap，不修改生产库或旧环境。

1. 在 permit 尚未签发、项目仍暂停时，核新 release 的 central/SEO/GEO pin、clean tree 与重新构建的顾问页面 manifest。cherry-pick 后中央 pin 按总控最终提交重新生成，不能把本地测试提交当云 runtime。
2. SQL 仅取新 SEO pin 中原有 `scripts/seo_distribution_media_schema.sql`。Git LF SHA256 为 `5e2f95f87a9a3df19144b57b24e2e6b7c67c900eaa02e3272274c362b0f923a8`，blob `89fbe1768453643b9c5f2a098f7d6508f8ba25b2`，与 b4 原文件相同；Windows CRLF raw SHA 为 `eb3d049be8b43d8f7987a5cca38f07e78af53fb055688188af9b5ab9e40c60e0`。不要用 CRLF hash 验证 Linux Git LF 字节。
3. 在已有独立库连接中先只读核 current_database/current_user、loopback/固定验收端口、search_path/current_schema、原生0105、外键目标 tenants/users/seo_sites/seo_distribution_variants 全在 acceptance_seo。三个 media 表应全部不存在；若只有部分存在或来源不明则停止，不凭 IF NOT EXISTS 掩盖差异。
4. 经总控批准，仅在同一事务 `SET LOCAL search_path=acceptance_seo` 后执行上述原文件。创建的对象为三表 `seo_distribution_media_sets`/`seo_distribution_media_bytes`/`seo_distribution_media_reviews`、索引 `seo_distribution_media_latest`、函数 `seo_distribution_media_immutable`、三个不可变 UPDATE/DELETE trigger。SQL 不创建任何 source/稿件/用户/审核数据，不变 Alembic stamp。核对所有对象及 FK referents 的 namespace 后才提交；异常回滚，不再运行整个初始化框架。
5. 按已审 release 用现有 activate/serve 流程更新仅独立验收服务。`GET /acceptance/health` 必须 native_head 为新 SEO pin；pilot_native_files 包含下面四项实际原生文件 raw SHA，seo_media_schema.source/hash/target_schema 匹配且 automatic_install=false。该 manifest 只审计源码字节，database_status 明确为 not_inspected_by_manifest，不能用它替代上一步真实结构核查。
6. 通过真实管理员 API 为100008分配site6，核当前身份；通过100007上传→100008实际预览及审核→当前顾问 source/assets 读取，核冻结 PNG/JPEG 的 sha/bytes/pixels 与 manifest。readiness/source_revision/digest 取实际接口结果，不能手改信任位或写伪source。
7. 原始60/variant1及母稿61v2正文保留。新封面就绪后由总控统一更新新驱动/permit冻结元数据并核一账号一篇；旧 TEMP 驱动仍固定94+b4+assets0，应该拒绝本批新 pin/source。完成实际 API/JWT/PG/设备封面读取和执行端约束前不要签唯一正式 task。

Linux Git LF 文件 SHA256（health 在 Linux 应与部署实际字节比较）：

| 原生文件 | SHA256 |
| --- | --- |
| app/seo_distribution_sources.py | 4c613c003d48612d8912701000071f52f461f9bb330e2c8ac4361f847570a28d |
| app/seo_distribution_media.py | 6f952db759b5d01af1da4560250a2955d88aa8890604be971256175da51381a8 |
| app/api/seo_distribution_media.py | ad7d0f136e19de07935d09d6b95e1d01575479bfc3eba760f2cc6fd2c5de60a9 |
| scripts/seo_distribution_media_schema.sql | 5e2f95f87a9a3df19144b57b24e2e6b7c67c900eaa02e3272274c362b0f923a8 |

## 本轮测试与证据

最终一次运行 **127 passed，0 failed/errors/skipped**：单篇门禁119项（原99项与20项受影响/新增覆盖），整合8项。覆盖错范围/角色/意图/路径、私有文件模拟权限、受控期限等待与回滚、封面契约/数量/摘要/版本、native拒绝/不可用、原生素材路由及Depends/PrivateMediaRoute绑定、未挂静态入口、缺失路由拒绝、GEO不导入素材、manifest只读审计和原生顾问分配门槛静态保留。

原生路由装载使用精确冻结源码，但 auth/storage 为显式 sentinel，仅证明真实路由代码的接线与依赖未丢失；不是实际 JWT/PG/HTTPS/客户审核或平台上传验收。期限测试是受控内存事务/时钟。没有为本批启动数据库或服务，也没有重复旧原生全套。此前原生封面自身14项实际PG与166项回归结果见原生冻结文档，不能计入本批127项或冒称本批真实云测试。

执行命令（在本分支，指定只读原生冻结目录）：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
$env:NATIVE_SEO_COVER_ROOT='D:/SNIPERS国内版/ai_sni-worktrees/seo-wechat-cover-acceptance-20261012'
& 'D:/SNIPERS国内版/ai_sni/.venv/Scripts/python.exe' -B -m pytest -q -p no:cacheprovider tests/test_distribution_single_publication_gate.py tests/test_distribution_cover_acceptance_integration.py --junitxml "$env:TEMP/distribution-cover-integration-tests-20261012/cover-central-integration.xml"
```

证据只放 TEMP `distribution-cover-integration-tests-20261012`，无客户全文、截图、JWT或密钥：

| 文件 | SHA256 |
| --- | --- |
| cover-central-integration.xml | c6c6a5be5a2c7370070456bc6b95ff810bfdf023978c11bb21903aae2e3752db |
| central-cover-evidence.json | 9183def4e8011ac6ea02ebdb79aeebfa0314e69b72f614777d10fbe9d7c08517 |

JSON 包含基线、代码pin/tree、原生pin、127项分组、五个中央文件及四个原生文件 raw/Git LF/hash/blob、未执行服务/DB/云/平台操作边界。文档在实现冻结后另行提交，代码字节与测试pin不因文档提交变化。

待总控实际验证：云安装namespace、真实管理员分配/当前顾问上传与独立审核、真实source/asset bytes、改封面失效/跨范围拒绝、唯一task双grant期限、执行端封面导入与提交、公开页检查和客户交付回传。本批未声明真实发布成功。

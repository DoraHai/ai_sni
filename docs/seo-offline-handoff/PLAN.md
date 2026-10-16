# 多号通离线交接最小改动方案

日期：2026-10-16。范围：单独安装多号通、人工发布、文件回填链接。仅实现“导出发布单”“导入回执”两个入口，不增加自动发布、调度、账号绑定、桌面联动或 `/api/distribution` 交接调用。

## 基线与现有入口

源码仓库：`D:\SNIPERS国内版\ai_sni`。从远程单独刷新 `origin/codex/production-seo`，基线为 `394ef0aa638066970a932fb0ba6f2d67b71265f8`（2026-10-16本次读取）。新分支：`codex/seo-offline-handoff-20261016`。

工作区：`D:\SNIPERS国内版\梳理-2026-10\duohaotong-access\handoff\worktree`，避免改动任何原工作区及其他分支。下列路径相对于该工作区；原始证据在上述基线提交中可复核。

| 能力 | 后端证据 | 前端证据 | 复用结论 |
|---|---|---|---|
| 已发布链接人工登记 | `app/api/seo.py` 的 `create_manual_publication`，POST `/api/v1/seo/content-distribution/publications/manual` | `frontend/src/views/seo/SeoDistributionView.vue` 的 `openManual/selectManualContent/saveManual`、“登记发布链接”；`frontend/src/api/seo.js` 的 `createSeoManualPublication` | 复用现有页面、内容确认/版本门禁、发布记录模型，保留原入口 |
| 人工任务完成回填 | `app/api/seo.py` 的 `complete_manual_publication`，POST `/api/v1/seo/content-distribution/publications/{publication_id}/complete` | 同页 `completeManual`、`completeSeoManualPublication` | 已有任务人工回报能力；本次不依赖创建自动分发任务 |
| Excel 发布链接批量登记 | `app/api/seo.py` 的 `download_published_links_template/import_published_links`，GET `/api/v1/seo/content-assets/published-links-template`、POST `/api/v1/seo/content-assets/import-published-links`；`app/seo_distribution_import.py` | 同页 `selectImport/previewImport/commitImport`、“Excel 批量登记”；`frontend/src/api/seo.js` 的 `importSeoPublishedLinks` | 复用上传→预检→人工提交的操作方式，原 XLSX 格式不变 |
| 已发布清单导出 | `app/api/seo_page_captures.py` 的发布清单导出路由；`app/seo_publication_export.py` | 同页 `exportPublicationList`、“导出发布清单”；`frontend/src/api/seoPublicationExport.js` | 这是事后发布事实清单，不是发前 JSON/CSV 发布单，保留原功能 |
| 离线发布材料包 | `app/api/seo.py` 的 `download_publication_materials`，POST `/api/v1/seo/content-distribution/publications/{publication_id}/materials`；`app/seo_distribution_package.py` | 同页 `downloadMaterials`；`frontend/src/api/seo.js` 的 `downloadSeoPublicationMaterials` | 原材料包依赖既有发布任务并可能下载配图；新格式只导出已有正文引用，不触发配图网络请求 |
| 发布记录与操作记录 | `app/models/seo.py` 的 `SeoContentPublication`、`SeoPublishAttempt` | 原发布任务/成功记录及操作记录界面 | 复用原表，不建立新的离线任务表 |

页面路由由 `frontend/src/seo-router.js` 注册 `SeoDistributionView.vue`。现有能力基本齐备，但没有面向这次人员交接约定的 JSON+CSV 发前发布单，也缺少“账号备注、三态结果、版本摘要”完整文件回执。因此仅补两个文件适配入口，复用原页面与数据模型，不改造多号通。

## 实现

1. 在原 SEO 分发页操作区增加 `SeoOfflineHandoff.vue`，仅有“导出发布单”“导入回执”两个按钮。编辑权限、客户/站点选择沿用原页面；身份或站点切换后清空旧文件预检、选择及账号，忽略旧请求的迟到结果。
2. POST `/api/v1/seo/content-assets/offline-handoff/export`：重新校验所选1至20篇当前审核/确认通过稿件及版本摘要；返回包含 JSON/CSV 发布单与回执模板的 ZIP。不写库、不产生发布任务，不调用平台或桌面端。排期只写进文件。
3. POST `/api/v1/seo/content-assets/offline-handoff/import-receipts`：复用 SEO 权限与稿件检查，`dry_run=true` 为默认预检，人工确认才 `dry_run=false`。格式由 `app/seo_offline_handoff.py` 校验，支持 UTF-8 JSON/CSV、25渠道完整名称、HTTPS链接、带时区时间与 published/failed/unknown。
4. 导入先按稿件ID排序加锁，整批检查后一次事务保存。持久化三态回执至 `SeoContentPublication`，账号及原稿证据保存至现有 `SeoPublishAttempt`。已有 published 不覆盖或降级；同内容重复导入幂等。只有 published 更新主稿发布状态。
5. 复用现有确认门禁函数；如果现有生产代码按旧数据库结构走兼容分支，本次沿用其行为，不新增迁移前置条件。未连接生产数据库核验其实际迁移版本。
6. 格式详见同目录 `FORMAT.md`。新增代码不调用旧自动发布函数，不接 `/api/distribution`，也不自动抓取回执链接。

## 数据库迁移

**本次不需要新增数据库迁移，也不执行任何迁移。** 使用现有 `seo_content_publications` 的 status、page_url、published_at、idempotency_key 等列，以及 `seo_publish_attempts` 的 JSONB 摘要字段保存账号与来源。unknown/failed 是记录字段值，没有新增表/列/约束。发布单与排期不落库。

该结论来自源码模型与已有迁移文件，不表示已登录生产核对数据库。若目标环境缺少生产分支原本要求的历史表结构，需要另行处置，不能借本任务执行迁移。

## 验证与交付

- 合成数据单元测试覆盖编码、CSV正文换行、25渠道前后端一致性、HTTPS、时区、三态、不合法状态、文件/行数限制、租户/站点越权、未审核稿、确认失败、旧稿版本/摘要、预检无写入、整批失败、重复幂等、成功保护及并发回滚。
- 前端执行真实组件处理函数，验证导出快照、预检后提交同一文件、客户/站点/登录身份切换、迟到响应；执行 SEO 构建及构建校验，回归原人工登记和发布清单测试。
- 使用独立合成配置、模拟数据库会话；不读取生产数据、不运行实际发布、不启动生产服务。
- 提交并只推送本任务分支，用 gh 创建目标为 `codex/production-seo` 的 draft PR，描述明确“不合并、不上线”。所有交付文档位于本目录，并在 PR 内附带 FORMAT、PLAN 的副本便于评审。
- 最终 `report.md` 写明 PR、测试结果、迁移结论、限制/卡点和模型名。使用 `C:\Tools\ossutil\ossutil.exe` 将三个 Markdown 上传到 `oss://snipers-video-transfer/duohaotong/handoff/`，不输出配置。

# UI-09 内容生产、审核与发布记录

2026-10-07。本地独立前端范围；后端契约核对 SEO 工作树 `f9a22877c090b9def66f0391e6fe5c6e2d6c5c7b` 的已有接口。未使用正在开发的 SEO-10 草稿生产实现。宿主仍为 UI-07 固定基线；仅修改 `customer-workbench/`。

## 已完成

- 已有 planned/drafting 稿件可由已分配顾问读取原字段、编辑标题/提纲/正文。要求服务端 `allowed_actions.edit_content === true` 和 `permission_basis.active_site_advisor_assignment === true`；客户不能编辑或提交。
- 先读准确 delivery，再以 tenant/site/content_id 精确 GET content-assets；校验稿件范围、版本、状态及显示正文。humanized_content 非空时只写该字段，否则只写 draft。不会将 delivery 合并正文同时写入两个字段；HTML 只按源码展示，服务端负责清洗。
- PATCH 只提交 version_count/title/outline/准确正文来源字段。保存后重新读取 delivery；旧确认是否失效以服务端版本和摘要为准。真实改动通常版本 +1；无改动可保持版本。
- submit-review 携带 version_count；已有关键词绑定和非空正文由服务端最终检查。review 提供明确“通过”和带意见“退回修改”；不自动退回 review/ready/published 以便编辑，也不通过 PATCH 修改业务状态。
- 发布记录 GET 按 tenant/site/content_id 范围读取，逐条校验 tenant/content/source_version。尝试记录只允许读取当前列表已有 ID。显示渠道、方式、状态、来源版本、链接、时间和错误；未知结果提示到平台人工核实，不自动重发或同步。
- 确认不等于发布；人工登记事实、系统 API 发布结果和页面核验分开说明。异常清空操作快照；身份/客户/站点变化清空编辑和记录；未知写入只允许重新读取核对。

## 准确接口

以下均以 `/api/v1/seo` 为前缀：

| 操作 | 方法和路径 | 本次范围 |
| --- | --- | --- |
| 原稿读取 | GET content-assets?tenant_id=&site_id=&content_id=&page=1&page_size=50 | 单一准确稿件 |
| 轻改 | PATCH content-assets/{id}?tenant_id= | version_count + title/outline + draft 或 humanized_content |
| 提交 | POST content-assets/{id}/submit-review?tenant_id= | version_count, note |
| 复核 | POST content-assets/{id}/review?tenant_id= | 原接口，增加显式退回 UI；版本/意见门禁 |
| 发布记录 | GET content-distribution/publications?tenant_id=&site_id=&content_id= | 只读 |
| 尝试记录 | GET content-distribution/publications/{id}/attempts?tenant_id=&site_id= | 只读 |

## 明确缺口与关闭的入口

1. `POST content-distribution/publications/manual` 当前没有 expected source_version/hash，无法原子绑定用户已读版本。本次无新建人工登记写入。
2. `POST content-distribution/publications/{id}/complete` 已有 source_version、当前确认及业务状态门禁，但 GET 列表缺少逐记录 allowed_actions。总控明确要求等待权威业务能力后再启用写按钮；本次没有该写方法或宿主白名单。不能仅凭 seo.content edit 或笼统 start_publication 推断可回填。
3. 人工回填后可能排队页面核验；排队不代表核验通过。UI-09 没有调用真实 complete、供应商、抓取或发布服务。
4. 固定宿主虽然注册 `/seo/content/editor` 和 `/seo/distribution`，业务实现与最新 SEO 不兼容：编辑器未按 site/content_id 精确查找，保存会同时组装 draft/humanized；分发页仍 PATCH content-assets 的 status/page_url/published_at。因此本批不提供这两个跳转。路由存在不构成安全业务入口的证据，也未修改旧模块。后续由总控协调新版宿主并核验，再考虑恢复受约束入口。
5. 本次内容生产指已有草稿编辑与审核；未接 AI 自动生成/新建内容、关键词绑定维护、富文本编辑器或真实平台发布。

## 本地验证

- `npm run test:ui09`：7/7；5 个契约用例和2个 Edge 流程。覆盖原正文来源、范围/版本/状态门禁、权限拒绝、409/403/503、未知写入不重试、迟到响应、编辑→审核退回→重提→通过→代确认、发布 GET/未知尝试、客户写入口关闭、窄屏。
- `npm run test:contracts`：28/28。复核测试补入真实顾问分配资格字段。
- `node --test connected-browser.test.mjs ui08-browser.test.mjs seo-execution-client.test.mjs`：8/8，既有确认/计划/四类执行链回归。
- `npm run test:ui06`：10/10（含与 contracts 重叠的8项），构建与真实 bundle 的受控浏览器检查。
- 本轮首次窄屏检查暴露旧稿件摘要不换行，已修正后通过。桌面编辑页截图人工查看，临时图片留 TEMP，不入库。
- 所有 API 为 loopback 假身份和内存夹具，构建检查为本地。没有真实凭据、数据库迁移、生产读取/写入、供应商调用、部署或推送。

提交后重建的 release-manifest 应记录当前 HEAD 且 sourceTreeClean=true。真实账号/服务端集成、发布登记能力、原宿主兼容和线上验收仍需后续安排。

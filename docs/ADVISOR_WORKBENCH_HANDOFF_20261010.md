# 顾问工作台前端交接

工作目录：`D:/SNIPERS国内版/ai_sni-worktrees/advisor-workbench-20261010`。
分支：`codex/advisor-workbench-20261010`。
生产 UI 基线：`1c079c988b76f36d7b4b9f44aaccd35ec85e9264`，从最新 `origin/codex/production-sem` 创建。

## 已实现

- `/customer-workbench/?console=advisor`，复用 canonical SEM session 和现有登录。登录/继续登录保留顾问入口。
- 只读 `auth/me`、`auth/modules` 与两个专用顾问聚合接口。绝不枚举客户再筛选顾问任务。
- 服务器身份核验、模块启用与 edit 权限预检；具体顾问分配仍由聚合接口授权。支持绑定客户的顾问，并再次校验绑定客户与返回记录一致。
- 每个模块每页最多 25 项，最大请求允许 50；游标严格递减，无跨页复制任务。筛选模块、真实阶段分组、当前页数量、月份、负责人、客户/范围、下一步人工动作和阻塞原因。
- AI 提案摘要与缺失资料使用 `workflow.ai_proposal`；不创造 AI 能力、数量或完成状态，不展示费用，不发起网站或业务写入。
- 401、403、账号/权限/模块会话变化和退出均清空列表并拒绝迟到响应。404/405/501/503 单模块展示未接入。
- 任务链接保留精确 `tenant_id` 和 SEO `site_id` / GEO `project_id`，附 `onsite_task_id`。入口校验唯一正整数及完整模块范围，登录返回保留任务 ID。

## 接口契约

`GET /api/v1/{seo|geo}/workbench/advisor-tasks?limit=25[&before_id=N][&tenant_id=N]`

响应：`{schema:1,module,items,next_before_id}`。items 沿用原 onsite record，附 `scope_name,tenant_name,next_action,blocker,capabilities`。scope_id 必须为正安全整数；module 与 workflow.module 一致；workflow.revision 为正整数；阶段为既有 draft/review/implementation/recheck/acceptance/done/cancelled。任务按 id 降序排列，next_before_id 为当前页最后一条记录 id 或 null；未知名称使用真实 ID。

客户端不提供通用 transport，不允许调用任意路由或写入。服务端须先按当前实名顾问的活动分配、客户绑定、scope 业务范围、模块权限和启用状态过滤，再分页；接口拒绝非顾问。不以 role_label 字符串推断顾问授权。

## 总控需接通的任务详情

根据总控后续所有权通知，本提交不修改 `connected-workbench.mjs` / `geo-workbench.mjs`，不修改 onsite-client/view 或两个 host adapter。

production-entry 已向两个 mount 函数传 `initialOnsiteTaskId: scope.onsiteTaskId`。总控应在两者接收这个可选参数；host.initialize 身份与范围通过后，调用 `readOnsiteDeepLink(client, initialOnsiteTaskId)`（来自 `js/advisor-task-link.mjs`），将 `{data,selected,before}` 放入原现场任务状态。SEO page 设为站内优化，GEO 沿用现场任务页面。

helper 只调用原 scoped client.list(task_id+1)，精确匹配任务 ID；不新增 detail API，不跳过 scope/revision 核验，不把聚合记录当作可写缓存。未找到明确显示不可见。总控若已独立完成相同逻辑，可保留其实现；入口参数名统一即可。

审查参考补丁保存在本机 TEMP：`C:/Users/Administrator/AppData/Local/Temp/advisor-deeplink-hooks-20261010.patch`。该补丁未纳入本提交，避免所有权冲突。

## 验证

- `npm run test:advisor`：10 项通过，含生产浏览器桌面/移动端、登录返回、仅查看账号入口关闭、模块降级、分页、筛选、403/退出清空与迟到响应、scope/版本/绑定校验。
- `npm run test:contracts`：原有 66 项通过。
- `node --test ui17-entry.test.mjs ui15-entry.test.mjs onsite-browser.test.mjs platform-console-browser.test.mjs`：6 项通过，原客户与超管导航及 SEO/GEO 人工站内流程保留。
- `frontend npm run build` 与 `npm run verify:sem-build`：通过，100 个 JS 产物。
- 移动端截图已人工查看：`C:/Users/Administrator/AppData/Local/Temp/advisor-workbench-mobile-20261010.png`，390px 无横向溢出。夹具仅存在测试中，不进入生产代码依赖。

尚需：总控合入任务详情接收参数后做两个模块深链端到端联调；后端聚合部署后进行实名顾问、跨顾问、模块撤权的真实只读验收。本轮仅本地提交，未合并/推送/部署，没有执行 DDL、供应商调用、网站写入或资金操作。

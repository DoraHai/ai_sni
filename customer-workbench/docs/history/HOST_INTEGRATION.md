# UI-06 宿主接入交接

当前：总控已选定同源独立 `/customer-workbench/`，已完成独立构建接线及本地编译产物验收，尚未注册生产路由或部署。`js/production-entry.mjs` 与 `scripts/build.mjs` 直接引用既有会话/登录源码；不复制维护鉴权、不新增token存储。构建、四文件产物、版本管理目标及原宿主最小补丁建议见 [BUILD_RELEASE.md](BUILD_RELEASE.md)。

分页已支持每页50篇、前后翻页与当前页重试；稿件/状态读取失败有重新读取入口，写失败不重发。三模块导航保留七种开通组合语义，SEM/GEO显示待接入且无业务请求；仅SEM/GEO开通显示能力待接入，不冒充SEO可用。后续UI-05条目保留接入依据，选路和50篇总量限制已由本节更新。

2026-10-07。本地会话适配器和连接 DOM 已实现，使用本机 HTTP 契约服务器完成浏览器联调。生产宿主尚未挂载，未部署或调用生产。SEO 契约依据：本地 `8ec3dbf0168032679853001f133b2bf634328f58`。

## 现有宿主与入口建议

只读参考 `D:/SNIPERS国内版/ai_sni-worktrees/automation-sem-frontend-20261007/frontend/src/` 的 `store/session.js`、`store/sessionStorage.js`、`auth/loginRedirect.js`、`api/client.js`、`router/index.js`；登记生产起点 `e494ea936dbddbd6f0198ec388bdbf030d12a391`。没有修改该仓库，生产一致性沿用总控结果。

宿主已有普通会话 token、user、tenantId、modules、authRevision 和同源 `/login?redirect=...`。setTenant 不发登录事件，modules 变化不保证增加 authRevision，因此桥接器同时观察身份、租户、站点和模块，不能只监听登录事件。

| 候选入口 | 接法与取舍 |
| --- | --- |
| 同源 `/customer-workbench/`（推荐） | 独立静态入口与发布产物，构建中引入现有 session/bootstrap 和 Vue watch，注入适配器。需服务器静态路由和既有会话启动代码进入构建；不能只复制 HTML 或自行读取旧存储 |
| Vue 路由 `/workspace/customer` | 现有路由组件直接引入 session/watch 并 mount，离开时 dispose。响应式接入直接，但与现有前端构建、布局和发布绑定 |

总控已选第一项，当前未注册生产路由；第二项仅保留历史方案。不新增域名、账号、登录系统或 token 持久化。

## 已实现

| 文件 | 能力 |
| --- | --- |
| js/host-session-adapter.mjs | 注入普通会话；auth/me、modules、tenants、sites 预检；同源固定 GET/POST/PUT 路径/字段/范围白名单；401退出跳转、403清空；身份或客户变化中止请求、丢弃迟到响应 |
| 同文件 existingSessionBridge | 使用既有 session/watch/getSiteId，观察独立 tenantId 变化及模块变化，不读写新存储或管理员 key |
| connected.html、js/connected-bootstrap.mjs | 独立连接入口；无宿主时明确断开、无 API 请求；不加载 DEV_ADAPTER；index.html 继续独立演示 |
| js/connected-workbench.mjs、css/connected.css | 列表/交付 DOM、本人确认/代确认/退回、精确版本复核、计划表单与保存状态、service-status L1/L2/L3；按钮以服务端 allowed_actions 为准 |
| 既有只读/workflow clients、contract-view、plan controller | 已挂载连接页面；版本/hash、真实 actor、计划 revision 和保存结果来自契约响应 |
| tests/fixture-host.mjs、tests/fixture-server.mjs | 本机假会话及内存 API 夹具，只监听127.0.0.1随机端口；不作为生产后端 |

宿主构建在 connected-bootstrap 前提供既有 session、Vue watch 与获授权站点选择，并执行：

```js
import { existingSessionBridge } from './js/host-session-adapter.mjs';
window.CUSTOMER_WORKBENCH_HOST = {
  ...existingSessionBridge({ session, watch, getSiteId: () => selectedSiteId.value }),
  redirectToLogin: url => window.location.assign(url),
};
```

缺客户/站点显示待选择，预检仍核对服务端范围。生产要求 HTTPS，allowLocalHttp 仅测试夹具显式开启。Vue 路由也可直接创建 adapter 并 mountConnectedWorkbench，卸载时 dispose。示例为接线说明，尚未改宿主构建。

## 本地运行与证据

本目录执行 `node tests/fixture-server.mjs`，打开输出的 `/fixture.html`；`/connected.html` 是无注入断开页。停止进程即停止服务。ES module 需 HTTP 宿主，不能双击 HTML 代替。生产产物必须排除 tests 与夹具。

`node --test host-session-adapter.test.mjs connected-browser.test.mjs`：**4 tests / 4 passed / 0 failed**。Edge 实际 DOM 覆盖列表/详情/本人确认/代确认/退回、计划保存/409/读后撤销403、service-status证据、未登录/401/403、切客户/身份迟到响应、390px手机布局、页面无错误、无外部请求；另验证路径白名单、跨客户拒绝与 tenantId 独立变化。复核客户端已有测试，本轮未宣称新增浏览器复核验收。

此前客户端/控制器20/20、只读客户端3/3与独立演示浏览器验证作为历史证据保留。本轮没有重复全仓或生产检查。

## 剩余工作

| 工作 | 状态与完成条件 |
| --- | --- |
| 真实宿主接线 | 独立构建及生产入口已完成，编译时直接复用现有session/login；原工作台跳转链接与静态路径仍待总控安排，未改模块源码 |
| 环境启用 | 由总控安排目标环境部署新SEO、0105、顾问active分配及双edit权限；本轮未执行 |
| 普通实名验收 | 获准环境/客户/站点范围确定后验证客户、分配顾问、未分配/撤销资格、冲突、0104；本地假会话不等于生产验收，目前无需交凭据 |
| 列表/轻改 | UI-06已完成分页，每页50篇；轻改、提交审核未挂载。复核按钮已接契约客户端 |
| 资料/关键词/消息 | 连接页面明确禁用，无模拟回退，不混入 service-plan，不假装消息发送 |
| 任务/发布/核验/报告历史 | 展示准备事实与证据引用，读取页面尚未挂载，不自动跟随端点；交付记录仅为本次读取稿件 |
| SEM/GEO | 本批连接模式只接 SEO；独立演示保留，不作跨客户汇总 |

确认不等于发布；0104 unavailable 禁用确认；ready 只表示事实就绪，任务完成须 done + 服务端核实 completion_evidence。计划 PUT 验证新revision、updated_by/updated_at 后才显示保存，后续编辑须重新GET资格。409/403/503/未知结果不显示成功、不自动重发。

回退点 checkpoints/UI-05-before。独立目录无Git仓库、提交SHA或PR；未提交、合并、部署、写生产客户数据。原r12和模块仓库未改。

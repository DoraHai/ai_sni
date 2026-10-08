# 宿主接入

生产构建使用 `js/production-entry.mjs`，固定同工作树的 `../frontend` 为会话源码。`session.js` 自身启动既有存储读取，`existingSessionBridge` 观察 token/user/tenant/site/authRevision/modules；客户变化不依赖登录事件。`loginRedirect.js` 处理原有同源登录跳转。没有另建登录或鉴权源码副本。

`js/host-session-adapter.mjs` 对普通会话进行 auth/me/modules/tenants/sites 预检，固定GET/POST/PUT白名单、scope和字段，拒绝任意URL和发布动作。401退出跳转，403清空；身份/范围变化中止与丢弃旧响应。无宿主配置的 connected.html 不发API，不回退演示。

`docs/host-entry.patch` 给现有工作台增加一个基于已选客户/活动站点的同源链接，排除demo，仅为review附件。缺少站点时独立页返回现有工作台选择，不能从URL授予权限。补丁未应用，组件和Vue路由均未修改。

构建/发布要求见BUILD_RELEASE；UI-05/06完整契约和原宿主读取证据见docs/history。后续生产路径、0105、顾问分配与实名验收由总控安排。

UI-12新增仅本机的HTTPS真实后端代理和登录接线宿主页，生产入口不变。它调用真实登录API返回值及原session.setAuth，覆盖原存储bootstrap；不声称原LoginView整页已验收。2026-10-08已完成部分真实API/PG业务联调，含本机真实PG认证目录桥的范围说明，详见 [实际结果](docs/UI12_ACTUAL_RESULTS.md)及[接线命令](docs/UI12_LOCAL_INTEGRATION.md)。

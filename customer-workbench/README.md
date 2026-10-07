# 客户工作台

SEM / SEO / GEO 共享客户空间的独立前端，拟定同源入口 `/customer-workbench/`。当前连接模式实际接入 SEO 契约；SEM/GEO 显示开通状态及待接入，不伪造业务结果。尚未部署。

## 构建与测试

在本目录执行（Node 24、npm，浏览器测试需本机 Edge 或 EDGE_BINARY）：

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm run test:contracts
npm run test:connected
npm run test:ui06
npm run test:ui08
npm run test:ui09
npm run test:demo
```

构建固定读取同一工作树 `../frontend/src/store/session.js`、`sessionStorage.js`、`../frontend/src/auth/loginRedirect.js`；不需个人路径或宿主环境变量，不建立新会话存储。产物在 `dist/customer-workbench/`，不会构建或修改原管理后台。

`npm run preview:fixture` 启动127.0.0.1内存API服务器，打开输出的 `/fixture.html`。假身份、假数据仅用于契约联调，不连生产。`connected.html` 无宿主注入时显示断开；`index.html` 是独立演示，不能作为生产入口。

## 范围与交接

- 已接：准确版本草稿轻改、提交审核、显式复核退回、发布记录/尝试只读；SEO列表分页、交付稿、确认/代确认/退回、复核、服务计划与周期、准备状态；四类执行链列表/详情/历史/依据、接续/单页重试/取消/顾问报告说明和冻结HTML下载；身份和客户变化清空，写结果不明只重读。
- 未接：基础资料、关键词维护、消息、新建/AI内容生产、渠道发布/人工登记写入、原始快照及整改子任务详情、手动新建执行链和SEM/GEO真实接口；页面明确禁用或列明边界，详见[UI-09交接](docs/UI09_CONTENT_OPERATIONS.md)和[UI-08交接](docs/UI08_EXECUTIONS.md)。
- 确认不是发布，ready不是任务完成，0104确认不可用保持禁用。后端最终判断操作资格。

[构建发布准备](BUILD_RELEASE.md) · [当前交接](HANDOFF.md) · [归档记录](UI_PROGRESS.md) · [宿主入口建议补丁](docs/host-entry.patch)。补丁仅供review，未应用到原组件。

`docs/history/` 保留UI-02至UI-06的开发证据，里面的绝对路径、旧未提交状态和外部文档链接是历史记录，不是当前构建依赖。冻结r12、临时截图、node_modules、dist和历史检查点不入本次提交。

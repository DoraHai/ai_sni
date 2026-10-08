# 客户工作台

SEM / SEO / GEO 共享客户空间的独立前端，拟定同源入口 `/customer-workbench/`。当前连接模式实际接入 SEO 契约；SEM/GEO 显示开通状态及待接入，不伪造业务结果。尚未部署。

## 构建与测试

在本目录执行（Node 24、npm，浏览器测试需本机 Edge 或 EDGE_BINARY）：

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm run test:contracts
npm run test:ui13
npm run test:ui14
npm run test:ui15
npm run test:ui11
npm run test:ui12-host
npm run test:demo
```

构建固定读取同一工作树 `../frontend/src/store/session.js`、`sessionStorage.js`、`../frontend/src/auth/loginRedirect.js`；不需个人路径或宿主环境变量，不建立新会话存储。产物在 `dist/customer-workbench/`，不会构建或修改原管理后台。

`npm run preview:fixture` 启动127.0.0.1内存API服务器，打开输出的 `/fixture.html`。假身份、假数据仅用于契约联调，不连生产。`connected.html` 无宿主注入时显示断开；`index.html` 是独立演示，不能作为生产入口。

## 范围与交接

UI15功能冻结后的正式上线检查见 [普通客户/顾问一次性最小验收](docs/PRODUCTION_MINIMAL_ACCEPTANCE.md)。清单只列待指定范围和一次执行步骤，不表示生产验收已完成。

UI-11补充计划、请求和响应模型来源，以及目标对象完成证据与全站效果背景的分别展示；保留旧完成证据。见 [UI-11兼容补丁](docs/UI11_EVIDENCE_DISPLAY.md)。

UI-12已运行本机真实API/PG的确认、版本冲突、撤权及合成事实人工登记链；任务因页面采集关闭保持未完成。实际结果和仍未解决的体验问题见 [实际联调记录](docs/UI12_ACTUAL_RESULTS.md)，命令与场景见 [本机联调接线](docs/UI12_LOCAL_INTEGRATION.md)。该记录保留UI12当时的问题。UI13已完成本批可用化，见[UI13验收与边界](docs/UI13_USABILITY_ACCEPTANCE.md)。

- 已接：独立资格的四类手动触发、默认关闭的AI草稿授权与同站点资料/关键词选择、准确版本人工登记和逐记录回填；准确版本草稿轻改、提交审核、显式复核退回、发布记录/尝试只读；SEO列表分页、交付稿、确认/代确认/退回、复核、服务计划与周期、准备状态；四类执行链列表/详情/历史/依据、接续/单页重试/取消/顾问报告说明和冻结HTML下载；身份和客户变化清空，写结果不明只重读。
- UI13新增：输入保护、独立首页、角色视图、安全正文预览、服务器分页发布交付历史、数据明细及查询、顾问资料新增/编辑和关键词新增/优先级/目标页维护。
- UI14新增：正文图片、原尺寸查看/关闭/重试、未完整查看提醒、内容搜索/筛选及详情返回位置；大量隔离数据验收与客户/顾问沟通接口缺口见 [UI14验收](docs/UI14_READING_ACCEPTANCE.md)。
- UI15新增：当前稿件的人工文本沟通、服务端实名/时间、分页/未读、显式已读及幂等发送恢复；需要SEO0106消息契约。验收证据与边界见 [UI15验收](docs/UI15_CONVERSATION_ACCEPTANCE.md)。
- 未接：富文本编辑、单次AI assist和平台真实执行、原始快照及整改子任务详情和SEM/GEO真实接口；页面列明边界，详见[UI-10交接](docs/UI10_EXPLICIT_ACTIONS.md)、[UI-09交接](docs/UI09_CONTENT_OPERATIONS.md)和[UI-08交接](docs/UI08_EXECUTIONS.md)。
- 确认不是发布，ready不是任务完成，0104确认不可用保持禁用。后端最终判断操作资格。

[构建发布准备](BUILD_RELEASE.md) · [当前交接](HANDOFF.md) · [归档记录](UI_PROGRESS.md) · [宿主入口建议补丁](docs/host-entry.patch)。补丁仅供review，未应用到原组件。

`docs/history/` 保留UI-02至UI-06的开发证据，里面的绝对路径、旧未提交状态和外部文档链接是历史记录，不是当前构建依赖。冻结r12、临时截图、node_modules、dist和历史检查点不入本次提交。

# UI-07 本地版本归档记录

2026-10-07。总控明确要求从已核验宿主基线归档独立前端到Git，并本地提交，禁止推送/合并/部署。已读取本基线AGENTS.md及HANDOVER的模块/发布边界；按本轮明确指定的e494ea936dbddbd6f0198ec388bdbf030d12a391起点执行，不以历史旧分支替换该基线。

## 工作树与归档范围

- 聊天无已附加可用工作树；既有同基线automation-sem-frontend工作树属于模块开发，未挪用。
- App managed create_worktree 返回Not a git repository；按授权使用主仓库git worktree add新建分支 `codex/customer-workbench-20261007`。未init父目录、未reset或改原分支。主工作区原有未跟踪docs和ossutil_output保持原状。
- 产品源归入 customer-workbench/，不纳入node_modules、dist、截图、凭据、baseline-r12或checkpoints。原非Git目录和原r12保留。
- UI-02至UI-06的交接/契约证据归入docs/history；历史绝对路径和“未提交”状态仅是当时记录。当前README/HANDOFF/HOST_INTEGRATION/BUILD_RELEASE以仓库相对路径为准。

## 迁入调整

1. build固定使用同工作树 ../frontend 的现有会话/登录源码，删除个人绝对目录环境依赖；manifest增加sourceTreeClean，提交后重建记录唯一HEAD。
2. 所有浏览器测试使用本项目package-lock的puppeteer，支持EDGE_BINARY；删除演示中指向未归档baseline副本的死链接。
3. 原宿主建议以docs/host-entry.patch提供，git apply --check通过。只包含计算入口和链接，未应用到组件。
4. .gitattributes固定本产品文本LF，补丁允许标准空白上下文；git diff --cached --check通过。原frontend/backend/router/迁移没有改动。

## 实际验证

在新工作树 customer-workbench 内安装锁定依赖并验证：

| 命令 | 结果 |
| --- | --- |
| npm ci --ignore-scripts --no-audit --no-fund | 成功，109个依赖，仅本目录node_modules且被忽略 |
| npm run build | 成功，无宿主路径环境变量，四文件独立产物 |
| npm run test:contracts | 28/28通过 |
| npm run test:ui06（含pretest构建） | 10/10通过，包含上项中的8项，不重复计为额外独立用例 |
| npm run test:connected | 最终1/1通过，列表/确认/代确认/退回/计划/状态/401/403/409/迟到响应 |
| npm run test:demo | ALL PASS，七组合、共享角色、版本失效、六环节、手机与无网络 |
| git apply --check customer-workbench/docs/host-entry.patch | 通过，未应用 |

测试过程保留：首次复跑旧UI-05浏览器测试，其宽泛data-action选择器先等待、再点击到UI-06新增的禁用模块按钮，分别超时/找不到列表；将等待及点击都限定到.navigation后链路通过。这是旧测试定位问题，无需修改业务行为。未运行模块全仓或生产测试。

所有契约调用均为本机假身份/内存API；编译产物在虚拟HTTPS拦截环境验证现有存储和同源登录，不请求真实账号。提交前构建sourceTreeClean=false符合本地验证状态，不能当作生产发布证据；提交后按BUILD_RELEASE从HEAD重建并检查true，提交SHA由Git与最终交接回报给出，避免在同一提交内容内循环写自身SHA。

后续仍需总控安排推送/PR/合并、原宿主入口与静态路径、SEO新版本/0105/顾问分配及实名试点验收。本批不执行这些动作。

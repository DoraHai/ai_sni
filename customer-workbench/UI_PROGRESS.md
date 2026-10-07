# 客户工作台开发进度

## UI-08 / 2026-10-07 / 实际执行链页面

本批沿用已归档工作树及分支，起点00576b57。按SEO本地f9a22877c090b9def66f0391e6fe5c6e2d6c5c7b读取确切API文档，并窄读执行投影、任务payload、周期计划和排名/页面/报告处理源码；不改SEO仓库。

新增execution client/view、cycle config，实际挂载四类执行链到进度列表/详情。展示周期、等待角色、阻塞、历史/截断、任务和事实时间、页面/关键词引用及completion_evidence；与service-status准备状态分开。服务器允许的内容接续、周期接续、失败单页重试、取消、报告顾问说明均挂载；写后重新GET资格。报告按冻结元数据ETag及实际SHA256核验后下载HTML，从不注入DOM，不当PDF或发送。周期开关初始关闭，沿用服务端值，只有显式保存才PUT，展示范围与人工阶段；进入页面只GET。

新增tests/execution-fixture.mjs、seo-execution-client.test.mjs、ui08-browser.test.mjs与npm脚本。本批真实命令：test:contracts 28/28；test:connected 1/1；test:ui08首轮7/7。随后优化报告错误文案及页面/关键词依据展示为可读字段+折叠原始依据，再运行改动相关UI-08测试，最终7/7通过；构建成功。提交SHA以交接回报和Git记录为准。所有API均为本机契约服务，无生产账号/任务/采集。临时截图仅系统TEMP，不入提交。

相关文档README/HANDOFF/BUILD_RELEASE同步，详细接口映射和真正端到端剩余项见docs/UI08_EXECUTIONS.md。手动新建执行链缺前端trigger能力标志未推导资格；原始快照/整改子任务/内容制作与渠道操作尚未挂载。未推送、合并、部署或迁移，不重复模块全仓、生产审计和未改的演示全套。

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


## UI-09：准确草稿编辑与审核、发布记录只读

2026-10-07。实现与范围见 [UI09_CONTENT_OPERATIONS.md](docs/UI09_CONTENT_OPERATIONS.md)。顾问编辑/提交/复核以服务端资格与版本为准；客户仅确认/退回。人工登记写入缺原子新建版本契约和逐记录能力，按总控要求保持禁用。核查固定宿主原页面实现后撤下不兼容跳转，不修改旧模块。新增7项本地检查通过，既有契约/连接/执行链/构建继续回归。没有生产操作。


## UI-10：显式触发、AI授权与准确版本人工登记

2026-10-07。参照 SEO c8fa621e，具体契约与边界见 [UI10_EXPLICIT_ACTIONS.md](docs/UI10_EXPLICIT_ACTIONS.md)。只读事实最近500条且无total/分页，关键词支持同站点分页选择；内部ID输入不作为替代。触发不从计划编辑资格推导，未知结果保留UUID并读进度核对；人工登记准确版本与页面证据排队分开。旧模块跳转继续关闭，未改SEO/SEM目录。

最终定向验证：UI-10 9/9，与连接/执行客户端合并15/15；contracts 28/28；准确原字段客户端5/5；UI-06编译入口浏览器2/2。分组有重叠。既有UI-08/UI-09页面也完成相关回归。所有接口测试为本机夹具；Git diff --check通过，提交后重建与manifest由最终交接回报。没有推送或部署。

## UI-11：模型来源与目标完成证据显示

2026-10-07。对照SEO 67975f32，仅补计划/请求/响应模型的只读来源标签，以及completion_basis/scope限定的对象完成证据和独立effect_context背景。缺失响应模型不推断，历史完成证据按原字段保留，写入行为不变。详见 [UI11_EVIDENCE_DISPLAY.md](docs/UI11_EVIDENCE_DISPLAY.md)。定向验证4/4（含1项Edge只读页面），未重复全套；本地构建与Git空白检查通过，提交后重建记录由最终交接提供。总控已报告本机PG16.15验证10/10，阻塞解除；不是本聊天复跑或生产验证。未推送或部署。

## UI-12：本机真实联调接线准备

2026-10-07。增加仅loopback的HTTPS代理、原session.setAuth登录宿主页、真实API预检runner与完整角色场景。传输/浏览器接线探针最终2/2，语法与空白检查通过；真实FastAPI/PG业务结果仍未运行，不拿探针或原假业务服务器充当联调。测试登录宿主页不等于原LoginView验证码整页验收。SEO独占准备数据库，等总控环境放行后才运行实际登录/业务操作；本聊天没有写DB、生产、push、合并或部署。详见 [UI12_LOCAL_INTEGRATION.md](docs/UI12_LOCAL_INTEGRATION.md)。

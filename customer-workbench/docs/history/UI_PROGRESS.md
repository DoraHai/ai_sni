# 客户工作台开发进度

## UI-06 / 2026-10-07 / 独立构建、分页与重试（当前结果）

总控选定同源 `/customer-workbench/`，授权仅独立实现和发布准备；三模块共享架构不变，本批实际接口先SEO。回退点 checkpoints/UI-06-before。额度读取used=8%、remaining=92%，未到低于40%暂停阈值。

新增 `js/production-entry.mjs`、`scripts/build.mjs`、package.json/lock、.gitignore、BUILD_RELEASE.md。构建别名直接引用既有SEM前端 session/sessionStorage/loginRedirect 文件；不复制维护鉴权模块、不新增token存储。Vue锁版本3.5.35与宿主一致。已有会话模块本身执行启动读取，API预检继续服务端核验。参数只选择候选客户/站点，缺失或非法范围显示待选择并能返回现有工作台；401及未登录使用原同源登录helper，保留合法范围。

`seo-readonly-client.mjs`增加page/pageSize、输入与响应页码校验；连接DOM增加前后翻页、当前页刷新、列表缩短提示、失败清旧列表、稿件/状态重读。写入失败只能重新读取核对，不自动重发。切身份/客户复位第一页。保留SEM/SEO/GEO模块入口，按服务端开通显示：未开通、已开通待接入、SEO可使用；七种组合已测。只开SEM/GEO显示能力待接入，不能误作客户无权限或编造业务成功。SEM/GEO业务API未调用。

构建来源：SEM e494ea936dbddbd6f0198ec388bdbf030d12a391。`npm run build`通过，输出 dist/customer-workbench 的index.html/app.js/app.css/release-manifest.json；包含上游提交、原会话逐文件hash、独立源码/lock与产物hash。构建拒绝上游会话/lock脏改、Vue锁不一致、演示代码入图及额外旧产物。只写本目录，无生产路由改动。

验证：`npm run test:ui06`（pretest先构建）**10 tests / 10 passed / 0 failed**。8个单测覆盖分页/响应错页/跨范围/登录返回/tenant独立变化，2个Edge用例覆盖53篇前后分页、500/503重读、写失败不重发、列表缩短、范围切换、七种模块组合、390px、实际编译产物读取原sem_auth_v1、无新增token存储、无登录/401返回同源及范围参数。所有HTTP落到本机内存服务器；编译产物使用浏览器拦截的虚拟HTTPS源，无外部请求或生产账号。

保留测试过程：首次浏览器启动早于npm依赖安装完成，产生ERR_MODULE_NOT_FOUND；等待安装完成后重跑。随后读取500只显示错误码而非重试提示，测试超时，已修正错误消息映射和状态等待后10/10通过。最后将SEM/GEO-only无SEO情况改成“模块待接入”而非“无权”状态，重建成功，并仅复验相关分页/七组合浏览器用例1/1通过。未重复全仓或原演示全套。

版本管理建议：现有主仓库 customer-workbench/ 独立目录，在总控安排的工作树/分支落库；未在父目录或本目录初始化Git。原宿主最小补丁建议只改 AcquisitionCockpitView.vue 的computed链接与选择框后入口；不抽取/重写鉴权，不改router，本窗口未应用。发布需同源静态路径和四文件原子切换/回滚。详细清单与源文件接法见 BUILD_RELEASE.md。

剩余：总控落库/审查及原宿主跳转入口、生产静态路径、SEO新版本/0105/顾问分配和普通实名验收；轻改/资料/关键词/消息/完整任务证据历史仍未挂载，SEM/GEO真实接口另列。未提交、PR、合并、部署、迁移、真实客户读写；原r12及模块仓库未改。

## UI-05 / 2026-10-07 / 宿主适配与连接 DOM（历史结果）

本批要求已完成本地实现，生产宿主尚未接线。只读核对新 SEM 前端 session、loginRedirect、client 和路由；推荐同源 `/customer-workbench/` 独立入口，另一候选为 Vue `/workspace/customer`。具体构建/会话注入与取舍见 HOST_INTEGRATION.md；未修改模块仓库，不新建登录。

新增 host-session-adapter、existingSessionBridge、connected.html、connected-bootstrap、connected-workbench 和 connected.css。复用普通会话及既有身份/模块/客户/站点，严格同源固定路径 GET/POST/PUT；无登录、401/403、身份/客户/站点变化清空，迟到响应不进入新空间。连接页面已实际挂载列表、交付稿、确认/代确认/退回、精确版本复核、计划保存控制器和服务状态 L1/L2/L3；不加载 DEV_ADAPTER。资料、关键词、消息、轻改、发布与完整历史明确未接入。列表当前第一页最多50篇。

新增 tests/fixture-host.mjs、tests/fixture-server.mjs、host-session-adapter.test.mjs、connected-browser.test.mjs。实际命令 `node --test host-session-adapter.test.mjs connected-browser.test.mjs`：**4/4通过，0失败**。Edge贯通列表/详情/本人确认/代确认/退回、计划PUT/409/读后撤销403、service-status证据、未登录/401/403、切客户/身份的迟到响应、390px无横溢出、无页面错误/外部请求；适配单测覆盖固定白名单/跨客户拒绝、tenantId独立变化。所有API只发127.0.0.1夹具，数据在内存；不代表生产权限或数据库验收。

复核浏览器按钮已挂载，客户端既有测试覆盖；未宣称本轮浏览器测试触发了复核。此前20/20客户端/控制器与3/3只读测试保留，不重复全仓测试或生产审计。

回退点 checkpoints/UI-05-before。HANDOFF、HOST_INTEGRATION及接口映射已同步。剩余：总控选定现有宿主入口并接线/构建；目标环境部署、0105、顾问分配与普通实名验收；后续轻改/分页/任务/证据历史/消息等。无Git提交SHA、无PR、未合并、未部署、未写生产。原r12未改，独立演示继续 index.html。

另以Edge截取1440×1000连接稿件页并目检：布局完整、稿件与动作可见、右侧消息明确禁用；截图放系统TEMP/ui05-connected-desktop.png。本机预览启动于 http://127.0.0.1:52651/fixture.html（仅当前进程存活期间有效，可用上述命令重启获得新地址）。

以下UI-04及更早条目为历史过程；其中“尚未挂载DOM”已由UI-05更新。

## UI-04.4 / 2026-10-07 / 8ec3dbf0契约修正收尾（历史结果）

需求：以服务端`allowed_actions.update_service_plan`替换计划写禁用占位；false/缺失保持禁用；版本冲突或资格撤销不显示保存成功；保留semantics/真实证据和0104不可用。实际读取新API文档并窄读GET/PUT/semantics源码，SEO HEAD=`8ec3dbf0168032679853001f133b2bf634328f58`，未修改模块仓库。此前UI-04.1–.3保留为历史。

文件与实现：

- `js/seo-workflow-client.mjs`：严格服务端true启用PUT，发读到的expected_revision；不使用宿主role/flag。检查成功响应revision递增、范围、updated_by与时间；PUT后丢弃计划资格，下一次保存前须重读GET。0104 unavailable拒绝确认类操作。
- `js/seo-contract-view.mjs`：增加servicePlanView与permission_basis拒绝说明，保留semantics及真实证据模板；confirmation_unavailable不显示确认/代确认/开始发布。ready仍只表示事实就绪。
- 新增`js/service-plan-controller.mjs`：提供可挂载的load/save/invalidate/getState与读取/保存中/成功/失败状态。等待服务器时saved=false，失败清旧数据与资格；身份或视图失效后迟到成功响应不显示成功。控制器尚未挂载当前本地模拟DOM。
- `seo-workflow-client.test.mjs`更新，新建`service-plan-controller.test.mjs`；HANDOFF/接口映射更新，并新增`HOST_INTEGRATION.md`明确宿主条件、具体文件、页面挂载及未完成项。

验证命令：`node --test seo-workflow-client.test.mjs service-plan-controller.test.mjs`。实际结果：**20 tests / 20 passed / 0 failed**。覆盖精确PUT、server false/缺失/非布尔值、版本409、GET后顾问分配撤销403、503、超时未知、异常成功响应、身份/视图变化、0104与真实证据语义。均为受控transport+接口夹具；没有生产写入或全仓检查。本轮未改浏览器布局/模拟业务行为，未重复浏览器全套。

契约缺口已解决：service-plan服务端资格、service-status语义/证据引用、0104不可用枚举。剩余工程工作见HOST_INTEGRATION：选择现有登录宿主与同源路由，复用普通实名会话和固定路径传输，挂载真实页面模式并排除DEV_ADAPTER，拆计划/资料/关键词表单，接真实列表/轻改/任务/历史/消息。管理员条件为获准环境部署、0105及顾问分配；本轮不执行。

提交/PR/部署：独立前端目录无Git分支或提交SHA，仍未提交、未建PR、未合并、未部署。SEO 8ec3dbf0为对方本地提交引用。额度本轮读取used=6%、remaining=94%。

## UI-04 / 2026-10-07 / SEO精确接口客户端与视图映射

契约依据：automation-seo-20261007/docs/SEO_AUTOMATION_API.md及SEO_AUTOMATION_PROGRESS.md；HEAD c536d625e8722390e46ec3b21c89f4938b1bcd9c，本地已提交、未部署。只读核对delivery/确认/服务计划/状态响应，未改SEO文件。

### UI-04.1 客户端

需求：按确切路径/字段接delivery、客户确认/退回、顾问代确认、精确版本review、service-plan、service-status。文件`js/seo-workflow-client.mjs`、`seo-workflow-client.test.mjs`。

实现：宿主注入授权transport+普通实名context；未连接禁止请求。快照绑定tenant/site/user/revision；动作只依server allowed_actions。confirm提交准确version/hash、decision/actor_mode/note；真实actor来自响应。plan写带expected_revision，不能混入关键词/品牌数据。403/409/503/未知写结果不模拟成功、无自动重发；异常或冲突清快照，重读后再操作。

实际验证：首次`node --test seo-workflow-client.test.mjs` 8/8通过，覆盖未连接、两确认模式、退回必填、server动作限制、409/403/503、review版本、plan修订/能力、事实状态、身份变化/未知写结果。

### UI-04.2 显示映射与缺口

文件`js/seo-contract-view.mjs`、`js/workbench.js`及同测试。服务端确认模式/actor/版本/时间映射与本地角色分开；confirmation.status=unavailable有明确提示。phase ready只表示事实就绪，缺失负责人/历史/完成证据保留null，不套用本地六状态。页面增加“SEO接口未连接宿主身份”，继续明确模拟。

追加显示测试后10/10通过；最后追加plan冲突需重读和异常确认响应丢快照用例，最终11/11通过。`node --check js/workbench.js`通过。此次UI仅增加连接说明，未重复全浏览器、只读客户端或模块全仓检查。

契约缺口已直接反馈总控：service-plan GET缺编辑资格（当前客户端需宿主独立核实canWriteServicePlan）；service-status仅事实汇总无流程时间线/责任人/回填/完成且不含A04；API文字枚举缺0104时unavailable。这些不靠前端模拟补齐。

状态：本独立目录无Git分支/提交SHA；未提交、无PR、未合并、未部署、未调用生产写接口、未读取凭据或改客户数据。客户端尚未挂载真实宿主，不代表已生产接通。没有新公共后端/表。

后续：总控对齐宿主身份与编辑资格后挂载受控transport；前端轻改/对象列表与真实消息仍按既有或确认契约分批接入。部署、0105迁移与顾问分配需管理员授权，不能凭本地测试启用真实确认。具体路径和缺口已同步HANDOFF/接口映射。

### UI-04.3 总控澄清后最终状态（覆盖上述中间资格设计）

总控要求service-plan GET补服务端allowed_actions，不在宿主另建资格逻辑。已移除宿主canWriteServicePlan授权路径；当前saveServicePlan始终PLAN_WRITE_CAPABILITY_UNAVAILABLE且无请求，等待确切字段后启用。生产connected模式只展示service-status事实准备情况，UI-03六种本地流程夹具不得混入；缺负责人/历史显示未提供。

实际最终测试`node --test seo-workflow-client.test.mjs` 11/11通过，计划测试现为“读取保留revision、缺服务端资格即使宿主传flag也禁用且无PUT”；中间plan写成功/冲突用例已替换，不宣称当前有可用计划写入。其余版本/hash、真实actor、403/409/503、未知写入、显示映射和异常响应失效测试保持通过。模块后续新字段等待总控传递，无生产调用。

## UI-03 / 2026-10-07 / 六环节统一进度明细

需求：六个SEO入口与共享进度显示统一状态、等待谁、下一步、异常、历史和证据；客户只确认稿件，代确认不是发布。关联UI-A01、SEO-A02–A07。文件：`js/adapter.js`、`js/workbench.js`、`verify.cjs`、`HANDOFF.md`、`落地清单与接口映射.md`及本文件。仅自己目录，无Git分支或提交SHA。

实现：本地progress夹具覆盖程序处理中、顾问待处理、客户待确认稿件、人工发布待回填、失败待处理、已完成。内容进度与同一稿件当前版本/状态同步，其余明确开发模拟。统一详情显示对象、版本、未知时间/期限、异常、下一步、历史和样例依据，支持固定L3/交付记录/对应稿件入口。“已完成”只作样例，不写真实完成；未知发布结果提示不盲重试。历史新动作保留模拟实际actor与本地时间。

验证：`node --check js/workbench.js`通过。首次浏览器验证预期初始六状态，但前面的UI-02测试已把稿件改为待顾问；断言收到两个顾问状态，正确反映共享稿件变化。测试调整为先刷新开发页面恢复初始夹具，再验证六状态；后续另验证代确认变成程序接续、尚未发布。最终结果见下方补充。

未接接口：统一状态/对象/版本、责任人、截止时间、异常恢复条件、历史actor与服务器时间、结果依据；人工发布准确版本/URL/时间回填和未知结果待核对。候选展示契约已记录到接口映射，不自建API/后端/表。

最终`node verify.cjs` ALL PASS：六入口明细/历史/依据、六初始状态、L3跳转、顾问代确认后未发布，以及直接相关UI-02共享身份/配置/7组合/手机/无网络。未重复只读客户端或全仓测试。

状态：未提交、无PR、未合并、未部署；无真实生成/采集/发布或客户数据修改。原r12未改。后续由总控传递SEO-01与六环节契约后替换适配器，不新增客户配置/报告审批，不扩大跨客户范围。

## UI-02 / 2026-10-07 / 顾问代确认、服务设置与完整SEO入口

依据：项目筹备目录 `SEO自动化实施总表.md`，UI-A01、SEO-A01–A07。开发目录为 client-workbench-local（不在Git仓库内，无本批分支/提交SHA）；模块代码仅参考，未修改。默认SEO，原r12冻结。额度读取used=1%、remaining=99%。

### UI-02.1 纠正规则与确认记录

需求：顾问可直接代确认，无需客户再次批准；记录实际actor、方式、时间和准确版本；修改失效。文件：`js/adapter.js`、`js/workbench.js`、`verify.cjs`。

实现：顾问确认动作独立标记confirmOnBehalf，保存模拟实名身份与ID，和客户本人记录区分。confirmationHistory保存历史，轻改/重新介入/退回后失效。只确认当前待确认版本，不把顾问复核当客户确认。全部修改首批保守使确认失效，不承诺排版自动豁免。

验证：`node verify.cjs`最终ALL PASS，包含顾问代确认身份/时间/版本、客户本人确认、失效历史。首次运行在手机尺寸下测试点击遮罩未能关闭满宽抽屉，导致找不到#materials；将测试选择器改为实际可见的`.drawer .close`后复跑通过，无需改产品流程。没有隐藏该次失败。

接口未接：SEO-01确认/代确认/准确版本review/允许动作契约，服务端资格、幂等和冲突返回。当前只有本地内存成功，不代表服务器已保存。

### UI-02.2 顾问设置与全流程入口

需求：资料、方向、关键词由顾问维护；客户不审批配置或签收报告。SEO不缩成单篇内容。文件：`js/adapter.js`、`js/workbench.js`、`css/workbench.css`、`verify.cjs`。

实现：服务设置入口仅顾问视图出现，保存模拟设置版本；客户调用模拟方法会拒绝，任务数量不增加。六个SEO工作入口：网站检查、关键词与搜索、内容、发布核验、数据报告、异常进度；复用固定L1-L3和交付记录，客户首页不放运营配置表。所有未接结果明确未知，不补0、不触发业务生成。

验证：最终`node verify.cjs` ALL PASS，含服务设置身份、无客户配置审批、六个入口、七模块组合、已有共享意见/可见范围、手机版与无网络。未重复全仓或原r12验证。

接口未接：顾问单客户授权，基础资料/服务计划/关键词的具体保存契约，服务周期/网站问题/排名/核验/报告/异常的结果与时间范围。当前已有品牌资料与关键词API仅列候选，无真实写入。报告签收不是本批客户任务。

### UI-02.3 可替换只读客户端与交接

需求：在已确认读取契约上准备受控客户端，不使用管理员凭据、不造生产写API。文件：`js/seo-readonly-client.mjs`、`seo-readonly-client.test.mjs`、`HANDOFF.md`、`落地清单与接口映射.md`、本文件。

实现：宿主注入已授权GET-only transport与tenant/site/revision，封装内容列表及经已授权列表验证的审核历史引用；拒绝外站对象，身份变化丢弃旧响应；401/403不降级为演示成功。不存token或key，不挂载到当前模拟UI，不新建共享后端/表。

验证：`node --test seo-readonly-client.test.mjs` 3/3通过，覆盖准确路径scope/GET-only、未验证内容拒绝、403、异站点、revision/site变化旧响应；`node verify.cjs` ALL PASS。客户端仍依赖宿主和后端最终鉴权，不能作为生产资格检查替代品。

## 本批状态与下一步

- 本批可体验入口：`index.html`。顶部切顾问查看代确认与服务设置；SEO工作查看六个环节；交付记录查看actor、版本与失效。
- 回退检查点：`checkpoints/UI-02-before`；原r12与模块仓库未改。
- 提交：未提交，无提交SHA。PR：未创建。合并：未执行。部署：未执行。真实生成、采集、发布、账号配置及客户数据修改：未执行。
- 下一批：总控传递SEO-01路径/字段/错误/版本/资格后，将确认适配器接入受控客户端；接普通用户宿主与经过权限过滤的只读结果。此处不预先发明确认路径。
- 剩余依赖：客户-顾问身份与单客户范围，允许动作；准确版本review/确认/代确认和失效；资料/方向/关键词保存契约；真实消息可见过滤与回执；各SEO结果/进度/证据契约。管理员与真人需求统一交总控，暂不索取凭据。

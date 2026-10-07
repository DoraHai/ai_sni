# 本地客户工作台交接

2026-10-07。独立客户前端窗口负责此目录，SEM/SEO/GEO 自动化与公共契约由总控协调。

UI-06当前结果：总控已选同源 `/customer-workbench/`。新增独立 production-entry 和可执行build，直接引用现有SEM的 session/sessionStorage/loginRedirect 源码并锁定Vue；产出 dist/customer-workbench 四文件及来源/产物hash清单，无新token存储。分页已可前后翻页（每页50篇），读取失败可重试，写失败只重读不重发。七种模块组合已验证，SEM/GEO开通仍标待接入。版本管理推荐既有主仓库 customer-workbench/ 独立目录，未初始化Git；详见 BUILD_RELEASE.md。UI-05下方“第一页限制/待选路”已由本节更新。

UI-05当前结果：`connected.html` 已挂载宿主适配器和真实契约DOM，包括列表、交付稿、本人确认/代确认/退回、复核、服务计划与准备状态。无宿主注入时明确断开，无API请求或演示回退。执行 `node tests/fixture-server.mjs` 打开打印的 `/fixture.html` 可体验本机假身份与内存API；模块入口需HTTP服务，不能双击代替宿主。`index.html`仍为原独立演示。

UI-05定向测试 `node --test host-session-adapter.test.mjs connected-browser.test.mjs` **4/4通过**，含Edge实际链路、401/403/409/资格撤销、无登录、切客户/身份迟到响应、手机宽度与无外部请求。原r12及模块仓库未改，回退点`checkpoints/UI-05-before`。

真实宿主尚未接线：推荐同源 `/customer-workbench/`，备选Vue `/workspace/customer`，具体接线/文件/限制见 `HOST_INTEGRATION.md`。本机测试不等于生产接通。未提交/PR/合并/部署/生产写入；基础资料、关键词、消息、轻改、发布和完整历史仍未挂载，列表当前最多50篇。

- 入口：`index.html`，用 Edge 打开。默认 SEO，保留七种模块组合。UI-02 已扩为完整 SEO 工作入口，单篇稿件用于体验确认主线，不代表全部 SEO 已实现。
- 冻结设计基线：原 `r12-tier-homes` 未修改；HTML/CSS/JS 副本在 `baseline-r12`。
- 实现：`js/adapter.js` 是显式本地模拟，`js/workbench.js` 是首页、详情、进度、数据与交付 UI；`css/r12-base.css` 保留既有样式，`css/workbench.css` 为局部布局。
- 客户与顾问共用同一演示客户空间、同一稿件/进度/对话。顶部身份切换明确为开发模拟，不代表真实鉴权。未开发顾问跨客户总览。
- UI-02 当前规则：顾问可代确认稿件，不需客户再次批准代确认。详情与交付记录显示“顾问李顾问（模拟）代确认”、实际actor、时间、准确版本；与客户本人确认分开。此前禁止顾问代确认的规则已作废。真实资格与允许动作最终由后端判断。
- 体验路径：顶部切顾问 → 打开 SEO 稿件 → 顾问代确认 v1 → 轻改保存 v2使旧确认失效 → 复核通过 → 客户本人确认或顾问代确认 v2。交付记录保留两类actor与失效历史；确认≠发布。首批所有内容变化保守失效，未宣称能识别纯排版豁免。
- 顾问专属“服务设置”维护基础资料、优化方向、关键词，本地保存不生成客户配置审批。客户只有稿件确认，不新增报告签收；SEO工作涵盖网站检查、关键词与搜索、内容、发布核验、数据报告、异常进度六个固定入口。
- 顾问可按需介入；客户可请求顾问。普通自动接续显示等待系统接口，不虚构完成。页面下方开发规则样例可选择轻改后顾问复核或系统检查，只影响下一次修改，不固化每步人工审核或AI自动发布。
- 对话/稿件意见标明客户或顾问模拟身份、客户可见消息或内部备注。客户视图隐藏内部备注；全部仍在本地内存，不是安全隔离实现，真实消息可见范围必须由后端过滤。
- 独立演示 index.html 的全部动作不联网、不写后端、不持久化；刷新即重置。消息标明未发送服务器或通知真人，AI服务未接通。任何本地确认都不是生产成功；SEM/GEO本轮只读，不扩写操作。
- UI-02 最新 `node verify.cjs` 已 ALL PASS：原相关验证及代确认actor/时间/版本、失效历史、顾问专属设置/客户无配置审批、六个SEO入口。`node --test seo-readonly-client.test.mjs` 3/3通过：GET准确scope、已验证内容引用、权限失败无mock回退、异站点拒绝、身份变化丢弃旧响应。未运行全仓检查。
- `js/seo-readonly-client.mjs` 与UI-04 workflow客户端已由UI-05连接DOM挂载；生产宿主接线仍待完成。
- UI-02 每步文件/验证/依赖和提交状态见 `UI_PROGRESS.md`；本批回退点 `checkpoints/UI-02-before`。
- UI-03 已补六入口统一进度卡片与详情：程序处理中、顾问待处理、客户待确认稿件、人工发布待回填、失败待处理、已完成。内容进度随同一稿件状态变化；其余为明确的本地状态夹具，不代表真实服务进度。详情保留等待人、下一步、异常、历史、L3依据和交付入口；代确认后仍显示尚未发布。
- UI-03统一进度数据契约仅为前端需求，见接口映射与UI_PROGRESS；服务端状态/责任人/期限/回填/结果依据尚未接通，不产生新配置或报告审批。
- UI-04 已对齐SEO本地提交`8ec3dbf0168032679853001f133b2bf634328f58`：`js/seo-workflow-client.mjs`读取并严格使用`allowed_actions.update_service_plan===true`，PUT带准确expected_revision；false/缺失不发送写请求，不接受宿主role/flag代授权。PUT不带新资格，成功后需重新GET才能再编辑。
- `js/service-plan-controller.mjs`与`js/seo-contract-view.mjs`新增服务计划可编辑/拒绝原因、读取/保存中/成功/失败状态。只有核实服务器新revision、updated_by、updated_at才显示成功；409/403/503、未知写结果、异常响应及身份变化均不显示成功且清旧资格。控制器已挂载UI-05连接页面；独立模拟页面继续使用自己的演示数据。
- 最新`node --test seo-workflow-client.test.mjs service-plan-controller.test.mjs` 20/20通过；只用受控transport和夹具，无生产请求。0104的`confirmation_unavailable/unavailable`保留，不显示确认、代确认或开始发布动作。`semantics`和真实证据模板原样保留，ready仍是事实就绪。
- 已解决的契约缺口：计划服务端资格、就绪度语义与证据引用、0104不可用枚举。剩余是真实宿主接线、任务与发布记录读取、部署/0105/站点顾问分配；本地页面挂载已由UI-05完成。具体文件和完成条件见`HOST_INTEGRATION.md`。基础资料/关键词继续独立接口，不混入service-plan。
- 本轮前回退检查点：`checkpoints/20261007-before-shared-space`；冻结 r12 仍未改。
- 原 r12 目录 `node verify.cjs` 也 ALL PASS：首页及数据层、28张表操作、30组模块期间、28次本地CSV下载、393个路由。新版首页已用 Edge 截图目检；临时截图在系统 TEMP。
- 详细复用清单、页面→接口→缺口和下一批边界见 `落地清单与接口映射.md`。
- 没有提交/合并/部署/OSS传输；本地新增目录即可回退至原 r12。凭据不在文档。
- GEO专项评估待补；不阻塞本地 UI。10/4–10/5记录原为用户回传；总控已于10/7独立核对生产版本与限定文件范围，见 [生产一致性核对](../../项目筹备-20261007/本地仓库生产一致性核对.md)，本窗口引用结果，无需重复核对。
- 已核对生产：SEM后端4d9c54f、前端e494ea9；SEO前后端d59d1a2c；GEO前后端2aa079cb；Auth63c67f。后端文件匹配SEM346/346、SEO397/397、GEO339/339；SEO前端58/58、GEO79/79匹配保留发布包。SEM/Auth前端仅核对版本标记，不扩大为全文件或全部功能验收。SEO本机schema0104，三个db均ok。
- 首轮旧代码和共享空间批次读取的d59d1a2c均为历史证据；当前UI-04接口依据已更新为8ec3dbf0168032679853001f133b2bf634328f58，见上方及接口映射。本地宿主夹具与页面联调已完成，普通实名生产宿主验收仍待完成。
- 总控已完成本地基线对齐，后续只读参考 [开发基线登记](../../项目筹备-20261007/开发基线登记.md)：`D:/SNIPERS国内版/ai_sni-worktrees/automation-sem-backend-20261007`、`automation-sem-frontend-20261007`、`automation-seo-20261007`、`automation-geo-20261007`。auth/client 参考新 SEM 前端目录，业务接口参考各自模块目录；准确起点 SHA 见接口映射中的路径表。客户前端仍在本独立目录，不整分支覆盖旧工作，不重复核对生产。
- UI-02 开始额度读取 usedPercent=1，remaining=99%；剩余低于40%暂停，避免轮询。

后续优先完成真实宿主接线；UI-05已实现固定路径GET/POST/PUT传输与页面控制器挂载。不得用开发modules/role参数授予资格。准确版本确认契约已到位，真实启用仍需部署、0105与顾问分配门禁。

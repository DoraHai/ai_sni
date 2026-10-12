# 公司执行电脑分发验收 · 2026-10-12

本轮已部署独立 Linux API／数据库验收环境，完成实际网页配对、公司 Windows 执行端绑定、原生 SEO 稿件准备及预检回执。扫码后的官方账号身份已匹配，执行端实际打开了官方空白图文编辑器。现已进一步部署原生公众号封面支持，通过实际命名 JWT 完成上传、素材回读、禁止自审、另一名已分配网站顾问审核及新来源读取。**完整真实发布尚未验收**：官方编辑器稿件导入、平台封面上传、单次提交、公开链接及工作台发布回传仍待执行；不得把内部素材上传算作平台发布。SEM 未部署或启用 AI 接管。

## 可复核的部署与仓库版本

| 单元 | 验收源提交 | GitHub 独立分支快照 | 完整源树 |
| --- | --- | --- | --- |
| 中央工作台／API | `1674c84c221b8027354bfaf12cd80fd6df617acd` | `097b7e1fb22c096d44180e1b0d3b0b6e3c79cff6` | `f23566c72c32ea779fd61faaa066395683806c2a` |
| 原生 SEO | `3087e62f23e799fe82d279f79f698f0499bf3a27` | `8b34c1578efc123f8e045696c59425ee00dd0c44` | `250882ffa7aa822f90561e5c91a68f0d8811cb57` |
| 原生 GEO | `46dacbd805afc00f37eba344306fde004039efed` | `8737194fdf6f0f2517fc831794a320d7a40e2fc0` | `259699522c8694171738972b23a32ad81a0ab0ed` |

GitHub 插件同步采用完整 UTF-8／mode 树与期望分支头校验，三个快照均与本地源树严格一致。未合并到 main；旧 SSH 身份仍不可用，改用已连接插件同步。GEO 历史共享文件只归档在独立 GEO 分支。

服务器目录 `/opt/gsnipers-distribution-acceptance`；数据库 `distribution_acceptance_seo`／`distribution_acceptance_geo`，独立 schema `acceptance_seo`／`acceptance_geo`。API 只监听 loopback HTTPS 55861／55862，通过本次独立 SSH 转发验收，不改变生产 Nginx 或生产数据库。三个自有服务未启用开机自动启动，未启动全域分发 worker。实际客户快照仅私有传输，不进入 Git。

## 早期配对与预检记录

| 环节 | 结果与边界 |
| --- | --- |
| 网页首次配对 | 原生命名账号登录；一次创建短码；真实 Electron 领取一次，服务器确认 claimed／设备 active。长期凭据只保存在执行端，外部 SID 权限规则为 0。 |
| 绑定与登录介入 | 初始 discovery 空；原生配置唯一 SEO15／站点6 绑定后 GUI 重读并选择。真实顾问 API 创建登录会话、读取官方二维码帧均 200。后续用户扫码后获得官方主页稳定 `gh_` 身份；原生服务器新建真实绑定，旧占位绑定已撤销并保留其不可变身份与历史。执行端新会话的当前身份精确匹配；总控独立复核新会话／绑定／scope／新鲜原生帧均 200。本轮同一个自有 profile 无需再次扫码。到期关闭会话，无静默续期。 |
| 网页身份与输入 | pagehide 清码、缓存恢复重新核验；慢网真实 GET 期间的名称／TTL 输入保留，离开后清空。相关前端 9 项回归通过，另有实际云浏览器验证，无响应模拟。 |
| 权限拦截 | 8 项实际云检查：客户不能配对／控制项目、外部客户不能读测试 scope／source、旧长期凭据创建口拒绝、Authorization／Origin／Sec-Fetch 的网页 claim 拒绝。两模块的真实目录只开放本单元。 |
| 原生 SEO 稿件 | 28 次实际 API 调用。派生母稿61 v2 ready、公众号稿2 revision1 approved，精确版本确认后 source-ready／eligible。审批是命名测试账号及 advisor_proxy，不等于真人内容批准。原母稿60／百家号稿1的正文、版本、状态保留。 |
| 单条任务与回执 | 原生顾问授权一条 preflight，云任务 `3228b482-ebde-434e-9e6e-d353ae8609ca`。PC 实际领取并执行一次，页面未核验时停止；没有平台写操作或 publication grant。经同任务结果桥接，初轮中央为 seq4 `HUMAN_REQUIRED`／`awaiting-human`，项目暂停 revision2。后续真实账号绑定流程停用旧占位绑定，保留原任务及回执，不复执行旧任务。 |
| 真实发布 | 未验收。编辑器导入、标题／排版／封面、提交发表、公开链接核验与原生发布回写均没有本轮成功证据。当前正式发布入口仍关闭。 |

## 已发现并处理的问题

1. GEO 的隔离目录入口与原生模块版本不兼容：修正验收入口后，两端实际 HTTPS／命名登录／模块目录复验通过；不修改共享原生鉴权。
2. 配对列表异步重绘擦除正在输入的字段：共享面板改为内存草稿、身份变化清空；本机延迟 DOM 回归及真实云延迟请求验证通过。
3. 隔离 SEO 超管目录显示了 SEM：独立入口保留真实 SEO 权限结果，仅将其他未服务模块标为不可用，两端实际严格 own-module 检查通过。
4. 初次预检把 `pending=0` 误判为最终回执确认：原 seq3 `PAGE_UNVERIFIED` 属于 localOnly，服务器只收到 seq2 DISPATCHED。原记录保留；同 task／lease／version／digest 追加新 seq4 `HUMAN_REQUIRED`，获得完整中央 ack，恢复执行次数为 0。未扩大 strict-v1 白名单，未延长 grant，未重发任务或伪造成功。

执行端修复已冻结在独立多号通提交 `710a1d7de90629a1b8ba2808ff171a0b57b98986`，工作区干净，静态复核未发现恢复闭环阻断。完整六字段 ack 在真实 exchange 校验后同事务持久化；历史总数与尚未确认结果分开；重启从同范围／版本／摘要／租约的持久回执恢复，不重新执行。typecheck 与四个文件中的 75 项相关测试通过；普通已确认记录和保留原 localOnly 的桥接记录，两种离线恢复入口均运行验证为本轮执行0／HTTP0。测试库中新加入 SQL 防修改触发器；实际旧库转送时采用仅追加策略，不能倒推旧历史已有这些触发器。详见多号通 `docs/ACTUAL_CLOUD_WINDOWS_ACCEPTANCE_20261012.md`。

## 扫码后的首次真实账号绑定

北京时间 16:33:36，用户完成本轮独立公众号扫码后，官方主页只读观察取得稳定 `gh_` 身份，账号名与主页截图一致；观察前后 URL 完全稳定，未保存 URL/query/token。当时原生远程帧为 200；16:34:03 登录会话到期关闭，无静默续期。这一证据确认该次登录，不代表后续会话仍已登录或拥有发布权限。

北京时间 16:39:54，总控使用命名超管原生 API 撤销旧占位绑定、建立新逻辑账号的真实绑定，并通过 GET 再核对。旧绑定的 external identity 未修改，原有任务／回执历史保留；没有复执行旧预检。项目仍为 SEO15／站点6、paused revision2、owner100007；没有新增任务或 publication grant。私有元数据证据为 `cloud-verified-wechat-binding-evidence.json`。

执行端按 device／binding／module／tenant／scope／account 确定独立 profile，原先没有跨新逻辑账号沿用本轮 profile 的安全路径。多号通在独立工作树补齐受约束的 metadata 重新关联：核对旧绑定撤销、旧会话与锁释放、新绑定真实范围一致，再取得全新的账号核验授权并重新读取当前官方身份；不读取、复制或导出 Cookie，不使用原多号通 profile。

旧绑定停用后，原生旧 session GET 实际返回 403 `REMOTE_SCOPE_FORBIDDEN`，不能当成关闭证明。总控在独立 `distribution_acceptance_seo`／`acceptance_seo` 内以 REPEATABLE READ READ ONLY 事务提取精确 session／controller／scope／device／binding 白名单元数据，确认该会话 state=closed、code=`BROKER_RESTARTED`、closed_at 与同 session 的 `remote_closed` 审计相符，旧绑定仍 inactive。没有重开旧绑定、改写会话状态或读取 nonce／Cookie 列。该固定指纹关闭证明仅用于本轮受约束登记入口，保留 GET403 的真实结果，不泛化为生产 API 已支持停用绑定历史读取。

北京时间 17:10:08，新账号核验会话的当前主页观察为 `IDENTITY_MATCH`。总控另行通过真实命名 JWT／受信 CA HTTPS 复核新 session、binding、scope、frame，均 200；设备／范围／binding／account／revision 均匹配，身份观察与原生帧均在 10 秒以内。页面截图再次显示相同公众号；没有再次扫码。项目仍 paused revision2，没有新任务、发布授权或编辑器写入。证据为 `cloud-real-binding-current-login-evidence.json` 与 `cloud-real-binding-home-frame.png`。随后本轮会话 close 200，执行端停止、窗口为零；不是常驻有效登录控制授权。

本地关联实现冻结于多号通干净提交 `36e62117b4ef69f52fba011ef1ffaa2fb2f28a52`，不可变包 `release/profile-reassociation-36e62117b4ef`；类型检查与 51 项相关回归通过。实际关联登记只执行一次，初次 CA 配置顺序失败与 8.3 路径比较失败均保留记录；没有关闭 TLS 验证或靠再次登记恢复。

静态复核发现新登记入口未提前完整检查根目录祖先及待写 SQLite／proof 叶子链接。总控实读本轮根至 C 盘共 9 层祖先、实际 DB 与 proof 叶子，均非 ReparsePoint，既有登录证据有效。路径修复在新的独立工作树干净冻结为 `33df23af29a23a0b4b6a1758c1b1bfe5c00bc225`，包 `release/profile-reassociation-33df23af29a2`；类型检查与 56 项定向回归通过，包含假 TEMP 祖先 junction、DB／sidecar／proof／history 叶子链接负例。未操作或重新登记真实 profile／registry。该修复为本地程序边界检查，未部署到生产服务器、未改变项目或发布权限。

发布稿件也经新的原生 GET 再核对，variant2 的 source revision／digest 与审核快照完全一致，标题 31 字、正文 2329 字、assets=[]；封面及官方发布必填项尚未核验。元数据证据为 `cloud-publish-source-readiness.json`。

## 最新封面与单次发布准备（北京时间 19:17）

独立环境通过既有 prepare/activate 脚本从上述冻结提交构建部署，没有重新 initialize 数据库，没有修改生产代码、数据库或 Nginx。实际 health 核对中央/原生 pin、标准顾问页面构建及四个原生素材文件 SHA。GEO 固定版本不变，未创建 GEO 发布任务。

原生 SQL 取 Git LF 字节，SHA256 `5e2f95f87a9a3df19144b57b24e2e6b7c67c900eaa02e3272274c362b0f923a8`。先核三表全部缺失，仅在独立 PostgreSQL 55483 的 `distribution_acceptance_seo` / `acceptance_seo` 事务中安装。随后真实只读事务证实三表的七个外键目标全部属于同一 namespace；原稿件行未重置。

管理员经原生顾问分配 API 为测试审核人100008分配site6。上传人100007上传一张1200×510 PNG，再以审核人身份读取实际数据库素材；SHA、41687字节及视觉与已核候选一致。上传使variant2 revision升为2并回到draft，原母稿61v2和正文/标题保持。100007自审实际403，稿件未变化；100008审核实际200。真实只读数据库确认上传者100007、稿件及素材审核者100008、状态approved及素材seal存在。这是命名验收身份的审核链测试，不代表真实客户完成内容审批。

新的实际 source revision 为 `seo-m2-v2-4940b1e683bbc04309686ca3d3ee522b9e0812302c6597cd97cb0bca2189728d`，digest为 `3a1b014a22e5d83d84711e7736a7740e140d674cce93ab0a7c8db8190895a62e`；恰一张封面。正文SHA仍为 `0f2d3bb31d010d20620d2264fc6c07d8e6635d7f1828b260c858198225514452`。内部审核响应与中央source响应因后者添加schema/platform/digest而不同，临时验收脚本曾作过严的完整dict比较而报错；没有重复审核，改以只读当前source及数据库复核确认已成功审核，原失败记录保留。

中央127项门禁/接线回归通过且独立复核未发现阻断；这些是受控合同测试，不能冒称真实云联测。另行实际 JWT/PG/HTTPS 已证实上传、自审拒绝、独立审核、来源及字节读取。20次实际权限/交付检查中，当前客户/外部客户素材读写403、匿名401、跨范围顾问403；顾问和当前客户均看到待发布，外部客户无法读取交付。无私有单篇permit时，正式publish仍403且任务数不增加。项目仍paused revision2，只有原已撤销预检任务。

独立顾问公网入口采用单独58443进程与根目录外的root-owned配置，冻结网关提交 `3790bef2b3528ee0428341c7506c29e660b55007`。服务器内实际GET200、公信证书TLS校验0，生产Nginx指纹不变；本机公网路径TLS中断且对应探测未到达服务器，已询问临时安全组放行。**公网访问尚未通过，不要求用户绕过TLS。** 本轮素材验收使用既有私有SSH转发。网关当前未暴露原生素材API，不能称公网顾问已能网页上传封面。防火墙许可仅两小时，服务不开机自启。

多号通已完成空白编辑器真实只读探测，正在冻结依赖原生task及两类grant的封面导入与单次提交适配。总控只在该执行适配就绪后签一个账号、一篇稿件的有限发布任务；来源、封面、范围、账号、期限任一改变均须拒绝旧授权。提交未知不能自动重试或伪造人工发布；须实际公开页检查后按原生顾问处理/发布回写，并验证双方工作台。此时尚未签发任务、未平台发稿。

新增私有证据：`native-cover-api-state-20261012.json`、`current-approved-seo-source-with-cover.json`、`native-reviewed-cover-preview.png`、`cloud-cover-real-auth-guards-before-publication.json`、`root-cover-integration-127.xml`；全文、密码、JWT、Cookie和设备密钥仍不入仓库。

## 早期后续计划（保留当时边界）

执行端新绑定的当前官方身份已精确匹配。已安排多号通在路径修复提交基础上的另一独立工作树开发受约束真实编辑器只读探测：新的账号核验会话中先匹配主页身份，仅许可官方空白文章 GET，检查当前标题／正文／图片控件与封面、声明等必填条件，保持保存、自动保存、上传和发表 POST 禁止。本批不填写稿件或恢复全域分发，尚在开发，不能算编辑器已通过。

随后再按精确 scope／version／digest 下发单条有限稿件导入任务，完成标题／全文回读；封面及选项准备完成后才进入受控单次提交、结果未知处理、公开链接核验及原生回写。现有正式发布入口仍关闭。每一步通过后才标记对应能力，不从登录、配对、素材交接或点击提交推断发布成功。

## 私有证据索引

主证据根：`C:/Users/Administrator/AppData/Local/Temp/distribution-cloud-pilot-20261012`。其中 `cloud-health-25ce3f99.json`、`cloud-admin-pairing-evidence.json`、`cloud-pairing-draft-browser-evidence.json`、`cloud-authorization-guards.json`、`cloud-native-module-catalog.json`、`cloud-single-preflight-before-outbox-race-fix.json`、`cloud-single-preflight-paused.json` 均为状态证据。密码、短码私密文件、设备密钥、Cookie、正文和控制 nonce 不纳入本报告或仓库。

独立后端配对 22 项原生 JWT／PostgreSQL／HTTPS 测试见 `DISTRIBUTION_DEVICE_PAIRING_HANDOFF_20261012.md`。多号通早期 42 项单元／GUI 供应商模拟测试不能替代本轮实际云及真实发布验收；9 项前端、8 项云权限检查、28 次原生 API 调用也不合并表述为完整发布通过。

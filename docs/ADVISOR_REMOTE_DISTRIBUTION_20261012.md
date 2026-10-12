# 顾问远程账号窗口 v1 前端

唯一写入目录：D:/SNIPERS国内版/ai_sni-worktrees/advisor-remote-distribution-20261012。
分支 codex/advisor-remote-distribution-20261012；共同基线257895ed37e098d7697fa1aa28e13eb87f4d2986；首轮checkpoint9c10ead8。
旧fb52顾问树及54e新版树保持只读。257完整保留54e自动工作流，仅增加分发接线/assignedScopes，无需补缺cherry。

## 权威合同与接线

只读中央checkpoint d8f7610a8010c43a2721e3c780fba99e2a5a8de4的 app/distribution_remote_contract.py、fixtures与docs/DISTRIBUTION_REMOTE_CONTROL_V1.md。
浏览器provider仅5operator路由：POST sessions，GET session/status，GET session/frame，POST input，POST close；不包含3device端点或device credential。
真实入口位于原顾问分发面板后方，使用distribution当前服务端账号绑定，仅wechat-article；客户delivery没有控制入口。沿用canonical session/JWT和原customer-workbench构建。服务端关闭/未部署返回诚实未接入。没有篡改SEM或平台页面。

## 控制与状态

600秒内会话；image/png同源Bearer fetch→Blob ObjectURL，2MiB、1920x1080、frame_seq/control_revision、5秒新鲜门槛。nonce仅在创建响应后保存在控制器闭包，快照不返回；device凭据不进入前端。UUID command单次发送；queued只显示排队，等待status ACK状态后刷新，不自动重发。
仅左键click、受限单键及1024字符文本；无modifier/URL/JS/桌面/剪贴板。文本输入为password控件，发送前清空；不记日志。作用域/账号选择变化立即清理；登录退出/会话通知立即清理；timer仅用于TTL和frame过期，不自动发命令。迟到header/body/frame均拒绝，清除并revoke ObjectURL。
UI开放account-login与account-verification；根据新权威合同7281f324，task-intervention入口从当前scope/binding已读任务取task_id/expected_source_revision/expected_content_digest。只显示wechat、未revoked、preflight/handoff、leased/running/awaiting-human且digest完整的任务；不显示publish/unknown任务介入。服务器派生full grant/lease，前端逐项匹配task/source/digest及合法UUID，不自报grant/lease。status不得把lease换成旧/新另一条；nonce/会话过期后不可复用。
关闭释放控制不恢复unknown、不恢复调度、不创建publication grant。登录成功不能由审计证明；素材交接/正式发布/公开页确认沿用原分发事实，正式发布关闭。服务端5operator鉴权、单顾问互斥与网络发布gate必须独立核验，前端隐藏入口不承担授权。

## 验证与边界

- 新增远程单元+HTTPS形状浏览器DOM8项通过：输入门槛/nonce/queued、PNG Blob、跨账号、退出、迟到响应、403、TTL/frame过期、越界/非法按键、固定5路由。
- 原contract191项、advisor38项通过。
- 原distribution回归47项通过。
- frontend npm run build及verify:sem-build通过（100JS）。customer-workbench原构建通过，仅4文件release，夹具不入bundle。

未生产部署、不DDL、不push；真实broker PG、真实HTTPS JWT及执行端测试账号/一渠道登录→验证码→交接→异常→关闭核验仍待root统一pilot。素材交接并非正式发布，未完成实页发布验收。

## 728 合同修正与真实host最小依赖

本轮仅追加任务映射与入口，target task单元3项+含任务按钮的HTTPS形状DOM1项通过；旧191/38/47不重复运行。7头GETframe以更新后中央合同为准；当前测试使用隔离供应器，并非真实broker联调通过。

编译真实顾问URL `/customer-workbench/?console=advisor`；无scope自动定位深链。native JWT登录需真实 `/api/v1/auth/me`、`/api/v1/auth/modules`；已分配范围可由 `/api/v1/seo/workbench/advisor-tasks?limit=25` 或 `/api/v1/seo/workbench/automation-projects?limit=25` 贡献。任一路真实404可降级，不能用虚构scope代替权限。
当前分发选择 `select[name=distribution_scope]` 值 `seo:15:6`，账号选择 `select[name=distribution_binding]` 为真实UUID；scope读取 `/api/distribution/v1/scope?module=seo&tenant_id=15&scope_id=6`。随后自动读取tasks/events/sources/account-schedules/project-channels/queue/plans/platform-directory/execution-progress（同scope query），部分真实404会降级，403会清空并关远程。任务按钮要求真实tasks结果含当前绑定及版本/digest。
控制selector：`[data-remote-action=open]`、`[data-remote-action=verify]`、`[data-remote-action=task][data-task-id=UUID]`；frame `.advisor-remote-frame`；图片通过七个header核对current session/device/frame/viewport。
close继续只释放控制，回交恢复显示待核验，沿用既有任务调查和项目控制；无虚假恢复按钮。

## 恢复后的只读画面轮询增量

只对current requested/active session约1秒串行GET status→PNG。一个读取在途时不并发，queued/delivered仅GET status等ACK；unknown清空session/nonce/画面，不重试命令或自动恢复。显式键鼠/text操作先取消在途读取，操作结果后才重新安排只读刷新。scope/退出/403/TTL/dispose后停止读取；取消的旧response不能创建Blob。连续3次读失败关闭能力等待人工重开，409无新鲜画面不算已执行。
合法current/fresh控制下刷新保留尚未发送的验证码，发送/换范围/失权立即清除。不将输入写入日志或持久化。公司专用Windows执行端、网页顾问的接入由root统一pilot，本增量不安装或启动执行软件。
最小新增验证：poller5项单元通过（串行、ACK门槛、停读、真实session取消/unknown清空），HTTPS形状DOM1项通过（不手点刷新也得到画面、自动读期间验证码保留、范围/退出清理）。旧191/38/47未重复；真实JWT/broker/device network联调仍待root启动后验证。

## 审查修正：未知结果的显式释放

unknown ACK、发送结果未知、连续3次读取失败使用disableControl：清图/输入、停止轮询，保留旧session与闭包nonce，仅用于显式close。status/frame/input和再次open均拒绝，界面提示待核验并保持关闭按钮可用。close成功才清除会话；close网络结果未知仍保留关闭资格，不自动重发。换scope/注销/403/TTL仍完全清除。不得把账号控制释放当作恢复未知任务或发布。
针对释放4项单元通过：unknown/3失败可close、真实输入网络结果未知及close失败可显式关闭、scope/logout/403/TTL全清。poller5项仍通过；原业务大套件不重复。

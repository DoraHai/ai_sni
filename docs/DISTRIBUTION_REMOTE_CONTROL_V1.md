# 远程账号窗口控制 v1

中央 broker 对接公司专用 Windows 电脑上的多号通，电脑主动向服务器领取任务和远程控制命令，顾问在网页操作。客户与顾问免安装多号通；本轮不建设云执行服务器。broker 本身跨平台，执行端只提供指定账号 BrowserWindow 的认证窗口。默认 `DISTRIBUTION_REMOTE_CONTROL_ENABLED=false`，只有值严格为 `true` 才启用，首轮仅 `wechat-article`。不返回桌面、任意网址、JS、文件路径、shell、剪贴板，不创建/恢复发布 grant。执行端必须通过网络级 gate 阻止正式提交/上传发布，账号登录不能扩张为发布授权。

所有消息严格 snake_case、`extra=forbid`，UUID 为字符串，所有时间为 UTC epoch 毫秒。Pydantic 权威源为 `app/distribution_remote_contract.py`。错误只返回固定 ASCII code，422 不回显输入。前缀 `/api/distribution/v1/remote`，所有响应 `Cache-Control:no-store`；JWT/device credential 仅 Authorization Bearer，不接受 query 参数凭据。

| 方法/端点 | 身份 | 请求/返回 |
| --- | --- | --- |
| POST `/sessions` | 当前实名 assigned advisor JWT | `SessionCreate`；`{schema:1,session:SessionView,control_nonce:<43字符>}` |
| GET `/sessions/{id}` | 同一当前顾问 JWT | `{schema:1,session:SessionView}`；不再次返回 nonce |
| GET `/sessions/{id}/frame` | 同一当前顾问 JWT | 二进制 image/png；7头 `X-Remote-Session-Id`, `X-Remote-Device-Id`, `X-Frame-Captured-At`, `X-Frame-Seq`, `X-Control-Revision`, `X-Viewport-Width`, `X-Viewport-Height`；全部由当前已鉴权session/最新frame派生；无可用新鲜图则409 |
| POST `/sessions/{id}/input` | 同一当前顾问 JWT+nonce | `SessionInput`；`{schema:1,command_id,command_seq,state:'queued'}` |
| POST `/sessions/{id}/close` | 同一当前顾问 JWT+nonce | `SessionClose`；`{schema:1,session:SessionView}` |
| POST `/device/poll` | 当前 device Bearer | `DevicePoll`；`{schema:1,broker_epoch,as_of,sessions:[SessionView],commands:[{session_id,command_id,command_seq,control_revision,frame_seq,input}]}` |
| POST `/device/frame` | 当前 device Bearer | raw PNG binary（不是base64/JSON）；见下方严格header；`{schema:1,frame_seq,control_revision}` |
| POST `/device/ack` | 当前 device Bearer | `DeviceAck`；`{schema:1,command_id,state,code}` |

`/device/frame` Content-Type 必须 image/png。仅使用以下元数据 header：`X-Remote-Device-Id`、`X-Remote-Session-Id`、`X-Frame-Seq`、`X-Control-Revision`、`X-Viewport-Width`、`X-Viewport-Height`、`X-Frame-Captured-At`。PNG至多2 MiB、1920×1080；viewport为账号网页CSS像素，执行端强制scaleFactor=1并核capture尺寸。PNG结构、尺寸和有界解压由服务器核查；不接受 desktop frame 或其他窗口ID。

会话固定600秒、无自动续时。同一device和账号最多一条有效会话，顾问不得抢占另一人的窗口。nonce仅通过创建HTTPS响应交给顾问，页面内存保存，数据库只有hash；截图和键盘文本只在broker有界内存中，PG仅有IDs/动作类别/状态/审计。不得记录截图、密码、验证码或输入摘要。审计不证明已登录/已发布。

输入仅左键单击、受限单键、最多1024字符文本，无modifier/shortcut、导航、JS、文件或剪贴板。必须引用服务器已通过顾问GET frame成功返回的近期 `frame_seq`，且 `control_revision` 仍为当前版本；图像从原 `captured_at` 起须在5秒内。每会话最多保留16条已返回帧的seq/revision/capture时间元数据，不额外保留PNG。同视口后来上传的新帧不让已看到的近期画面立即失效；从未返回、过期或旧revision的帧拒绝。已经接受的待处理命令按其原帧capture时间和当前revision检查交付，不因新上传或历史元数据容量淘汰而误判unknown。视口尺寸变化递增control_revision、清已返回帧历史并取消旧输入；关闭、撤权、过期、owner失效和重启也清历史。迟到图拒绝。每会话只允许一个待处理命令。command UUID只用一次，重复409；device poll至多10条会话/命令，立即返回（无longpoll），建议每500–1000ms调用。输入payload在第一次poll交付时移出内存，后续poll绝不重发；丢包/没有ACK属于unknown，不假称已执行，顾问通过新画面核对后重新开会话。ACK必须匹配完整session/command_seq/revision，执行端对command UUID也做去重，重启不重执行。

`account-login/account-verification` 不带task，可在project paused准备。顾问 `SessionCreate.task` 只接受 `{task_id,expected_source_revision,expected_content_digest}`，这三项来自正常顾问任务读模型；不接受浏览器自报grant/lease。broker在正确scope/binding下锁定当前task，再派生五字段 `SessionView.task={task_id,grant_id,lease_id,source_revision,content_digest}` 供device精确检查，并每次重验当前approved source、原动作/授权及lease。任务必须为当前顾问所有、项目 running 且控制版本保持一致，状态为 leased/running/awaiting-human，动作仅 preflight/handoff；首轮拒绝publish action或非null publication grant。关闭只释放控制，不把unknown结果改成未发布、不重新开启项目或授权。

broker是显式single-instance/single-worker服务。独立PG advisory owner连接保证一个namespace只有一个进程拥有内存；第二实例启动失败，不关闭第一实例会话。owner锁丢失即拒绝控制。成功取得锁后新broker_epoch关闭旧会话，清空旧输入/PNG；数据库内原 queued 变 canceled、原 delivered 变 unknown，不从数据库恢复input。至多8条内存有效会话，创建容量锁覆盖鉴权、数据库写入和最终commit；写入、审计或commit失败释放私有会话槽位。此生命周期不启动或修改SEM/GEO主调度器。

## 集成方法

`scripts/distribution_remote_schema.sql` 仅增加 `distribution_remote_sessions`、`distribution_remote_commands` 两张可选元数据表，依赖现有 `distribution_bindings/distribution_devices`。SQL须经审核后仅在目标namespace执行；本轮只在独立测试库执行，没有生产DDL。开关关闭时启动不查新表，不取得owner锁。

原 `app.api.distribution.router` 已包含 remote router，应用继续 `app.include_router(distribution.router)` 即可；独立factory也可仅 `app.include_router(distribution_remote.router)`。二选一，不能重复挂载。生命周期通过 `APIRouter(lifespan=...)` 管理，自动使用 `app.database.engine`；factory不要额外调用 `broker.start/stop`，不要使用多worker。owner使用独立数据库连接，不占普通API池连接。HTTPS必须验证服务器证书，JWT及现有device Bearer只放Authorization头。

公司电脑沿用现有设备凭据、绑定与授权机制；首次一次性配对流程留给后续小增量。外链/新闻源供应商API直发、平台差异排版后置，本轮不接入。SEM不变。

## 本轮验证边界

独立PG与真实原生SEO身份/分工/审批/source/中央task及lease已验证，HTTP消费截图与输入的执行端为合成测试端。测试不证明真实微信登录、验证码输入成功，也不证明多号通账号窗口的网络级发布拦截。公司电脑多号通GUI与标准顾问网页的实际接线、账号窗口范围、断网/验证码/未知结果提示由总控在独立pilot继续验收。正式发布保持关闭。

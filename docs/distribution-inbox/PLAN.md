# 多号通：无条件配对、发完回传、顾问事后标客户（只读方案）

状态：只读方案已完成三轮独立Cursor审查；前两轮问题已修订，第三轮PASS、blocking=[]，39个场景逐条核对。2026-10-19，北京时间，19:25前完成。本文的“新增、改为、应”均是建议，尚未实施；没有修改仓库、连接数据库或操作服务器。

## 最终操作流程（给用户看）

1. 顾问或超管打开统一的“多号通回传”页面，点“生成配对码”。不用选择客户、网站、项目、业务模块或平台；电脑备注可不填，自动取名。
2. 在多号通输入配对码，核对“结果交给谁”，完成配对。一台电脑可保留旧配对；新的通用配对单独显示，默认不自动上传。
3. 多号通自己发文，发完由人核对平台、公开链接、标题、账号名和结果，点“确认回传”。没有服务端稿件、没有“派给执行电脑”，同样能回传。成功需公开链接；失败、风控、需验证、审核中、结果未知可以没有链接。
4. 顾问在自己的“待标客户”收件箱看到结果，再选客户；如果客户同时开通 SEO 和 GEO，再明确选属于哪个模块。网站/项目可事后补，稿件可选关联。客户和模块不确定时继续留在收件箱，不猜归属。
5. 选定后，记录出现在对应客户的 SEO 或 GEO 发布记录页，注明“外部回传记录”。没关联稿件也能保存；有关联且满足原审核条件的稿件，可以核对公开页面正文。收到结果、操作人说发布成功、正文核验通过分开显示。

公众号只是平台列表中的一项。新链路不创建公众号连接，不要求任何账号连接、指定渠道、稿件或派单；账号名只是操作人上报的文字，不证明账号身份。系统不发邮件。

## 改动清单

- 服务端：新增独立的 v2 通用设备/收件箱接口、所有者隔离、人工标注和撤销、幂等与链接粗校验；保持 v1 原样。SEO 承担统一收件入口，GEO 复用共享数据库中的记录，分别负责本模块客户权限和发布记录视图。
- 网页：新增一个身份级“多号通回传”入口，SEO/GEO 原入口都能打开；把新建配对改成不带客户上下文的一键出码。原“顾问标注发布公众号”收敛为“标注发布账号”，客户归属和账号名分开编辑。
- 客户端：新增“独立结果回传”，平台、链接、标题、账号名、结果都来自本次发布操作或人工确认；不读浏览器存储来补信息。保留旧配对与待传队列，新旧协议不混用。
- 发布记录：新增外部记录的查询/展示适配，允许没有稿件；关联稿件是可撤销的引用，不直接改原稿件发布状态、服务任务、绩效或验收结果。这样避免造假稿件，也使改标客户不需要倒改原生发布账本。

## 迁移/env

**推荐需要一个独立迁移，新增两张小表；不需要新 env、新服务、新服务器路由或部署流程变更。** 旧“不能新增迁移”的上线授权不覆盖此项；本次仅写方案，不创建迁移、不提交或合并任何内容。未来实施时迁移须单独审查，未具备表结构时 v2 返回“功能尚未准备好”，v1 继续工作。

迁移只维护一份：未来实施先固定现有共享库迁移head，再在SEO线准备新的revision（本次不凭空指定编号），GEO线带入字节一致的revision/共享模型定义，不各自另编建表迁移。顺序为独立迁移审查及获授权的既有升级流程→SEO v2→GEO v2→0.3.7；GEO v2发布依赖共享库已具备同一revision及两表/必要索引。未就绪统一503 `INBOX_SCHEMA_NOT_READY`，只关闭v2入口，v1和既有服务照常；不得自动建表、后台补迁移、为SEM扩权或手工操作生产。本次只读不能验证线上升级状态。若现有流程无法在不改服务器配置/权限下完成，实施计划另列阻塞，不沿用“无需部署变更”的估计。

理由：现有回传账本放在客户 `tenant_modules.module_settings` 内，客户外键必填；用户表没有通用 JSON；SEO 发布表要求客户和稿件，GEO 发布表要求渠道稿。把无客户结果塞入任一真实客户、演示客户、占位公众号、聊天历史或 API 日志，都会引入错误归属、保留策略或权限语义。不能承诺合理的“零迁移”实现。证据见 S1、S2、S3、G1、X1。已查范围内未发现合适的无客户业务收件箱，不把这一判断表述成对全库所有表的证明。

最小可维护迁移是 `distribution_inbox_devices`（含待领取配对）和 `distribution_inbox_receipts`（原始结果+当前标注+JSON 修订历史）。不用另建公众号、客户、渠道、稿件或通用消息总线。一张“所有者大 JSON”理论上也能装两类对象，但会把每次上传、去重和标注都串到同一个大行，缺少直接的跨电脑唯一约束；不推荐作为省一张表的代价。

## 旧版兼容

0.3.5/0.3.6 已配对电脑继续走原 v1、原客户/范围/公众号绑定、原派单和回执格式，历史待传结果按原凭据送回原客户。**它们不能凭服务端升级就获得“无任务、任意平台”的能力。** 新通用码格式固定为 `DHT2:` 加 32 个 base64url 随机字符（CSPRNG 24字节，192位熵；总长37），冒号不属于 v1 字符集。新端按码类型进入独立宿主，不把旧凭据当通用凭据。旧端控件最多32字符，可能截断输入，宿主也会因冒号拒绝；旧端只能显示原有通用错误，不能承诺它会提示升级。新网页在展示码之前明确写“此码需要多号通0.3.7，旧版请先升级”。

“新链路任何一步不依赖公众号”与“旧版继续能用”的边界是：旧公众号链路作为明确标注的兼容区保留，新操作默认进入 v2；不扩建 v1 占位补丁。旧占位连接在最后一个使用它的设备、未完成任务、待传回执与核验结束前保留。结束后由有权限的人明确停用，历史记录保留，不自动删除，不用名称相同就认作占位连接。SEO 认 `config.duohaotong_placeholder`，GEO 认渠道 `content_rules.duohaotong_placeholder`，结合实际引用检查（S1:174、G2:248）。

## 是否 0.3.7

**必须出 0.3.7 才能使用完整新流程。** 0.3.6 的正式回传面板只显示服务端派来的稿件，命令要求模块、task/grant/version/digest，成功 URL 只认公众号短链（C1、C2）。升级不自动改旧授权、不自动认领或上传历史发布记录；旧数据保持原宿主归属。服务端先兼容上线、再发布客户端，但本次不实施任何上线或打包。

## 工时（SEO、GEO、客户端三路并行）

| 工作线 | 人时估计 | 内容与依赖 |
|---|---:|---|
| SEO/共享协议与收件箱 | 24–32 | 共享契约、两表迁移草案、身份级入口与权限、配对/接收、标注/改标/撤销、去重与清理；含 SEO 列表适配和正文核验接口 |
| GEO | 12–18 | 已开通模块/项目权限与提交前复核、外部记录列表、可选稿件关联和核验；不调用公众号专用设备接口 |
| 客户端 0.3.7 | 20–28 | 独立结果表单/发布结果接入、通用配对、固定SEO v2基址与精确传输白名单、独立安全存储/outbox/ACK、断网恢复、旧版兼容、打包 |
| 集成与两轮审计、修正 | 8–12（共享） | 合成数据联调、越权/重放/并发/旧端协议回归、界面复核；不登录真实账号 |

总工作量约 64–90 人时；三路有人并行、迁移审查及时且无新增范围时约 4–6 个工作日。前半天先冻结 v2 契约，三路可用合成 mock 并行。此估计不含迁移审批排期、真实平台自动发布器研发和真实平台账号验收；平台目录不等于已有可靠自动发文能力。

## 完整场景清单

证据缩写：S=SEO `4c40d0f`；G=GEO `e4d73c1`（合并 #778，与 `9465572` 对照）；C=客户端 `5bfacf5`/0.3.6；X=补充固定源码。所有路径及行号都指这些固定提交，不跟随移动工作树。证据只说明现有实现与差距，新行为尚未开发。表中“未查”是未取得真实样本/实际部署验证，不伪装已支持。

| 场景 | 处理方式 | 现有代码证据/差距 |
|---|---|---|
| 新电脑、新通用配对 | 身份级入口一键出码；自动备注；不传 tenant/scope/module/channel/account；10 分钟一次性码 | S `app/api/seo_distribution_report.py:88` 当前必填客户网站；G `app/geo/content/distribution_routes.py:83` 必填客户项目；需新增 v2 |
| 未选客户或只有 GEO 权限 | 身份会话可以配对及看自己的收件箱；不能借此访问 SEO 业务；标注时才检查目标模块 | X `app/security/advisor_tenant_auth.py:15,88` 现有精确会话白名单及选客户门禁，必须精确增补，不能简单复用旧路由 |
| 旧 0.3.5/0.3.6 已配对电脑 | v1 原样保留；历史任务、outbox 不迁到 v2；升级后可以另外添加通用配对 | C `src/main/distribution-report-host.ts:197,216`，`src/main/distribution-report-main.ts:25,62`；冻结 JSON shape 不改 |
| 旧端输入新码 | 网页先提示升级；旧控件截断/宿主格式拒绝，不承诺旧端新增提示。新端按 `DHT2:` 分流；领取不确定不自动再领 | C `src/main/distribution-report-host.ts:49,197`；`src/renderer/src/DistributionReportPanel.tsx:83` 32位输入限制 |
| 客户端v2传输与网页基址 | 客户端新增固定SEO v2路径白名单和独立宿主；GEO网页收件箱也用SEO身份API，不能沿用写死GEO v1路径和客户/项目参数的旧封装；GEO壳同源身份JWT、SEO收件API、GEO业务JWT三者在联调用例中明确隔离 | C `src/main/distribution-report-transport.ts:6,43`；G `frontend/src/api/geoDistributionReport.js:2,3` 已在57份主快照内；通用client本身baseURL为空，不能误说它自动加GEO前缀 |
| 今天上线的一键出码 | 保留“一键”和默认备注；新入口去掉客户选择与自动建公众号；旧区域标“旧版稿件派发” | S `frontend/src/views/seo/SeoDistributionReport.vue:54,88,154`；G `frontend/src/components/GeoDistributionReport.vue` 对应出码界面 |
| 今天上线的顾问标注发布公众号 | 旧记录仍可编辑；新记录改“发布账号”，所有平台同一字段；保留上报值和修订轨迹，不变成客户授权 | S `app/seo_distribution_report.py:154`；G `app/geo/content/distribution_report.py:568`，均已有账本级人工标注 |
| 现有占位公众号/账号 | 不增加新占位；只供旧 v1 引用，满足退场条件再人工停用，不删历史、不按名称误认真实连接 | S `app/seo_distribution_report.py:174`；G `app/geo/content/distribution_report.py:248` |
| 没派给执行电脑、没有服务端稿件 | 直接新建独立回传，只要已配对且本人确认；不要求 task/grant/稿件/平台账号连接 | C `src/main/distribution-report-host.ts:58` 旧命令强制任务授权；C `src/renderer/src/DistributionReportPanel.tsx:100` 无稿件无入口，需新增 |
| 公众号 | 接收公开短链和保留身份参数的长链，规则见平台表；同其他平台只作记录 | C `src/main/distribution-publication-url.ts:7` 有短/长链；但正式报告宿主 `distribution-report-host.ts:33` 只认短链，不能直接沿用 |
| 知乎、头条 | 按精确 hostname 和典型内容路径粗校验；不做账号归属判断 | C `src/main/distribution-publication-url.ts:14,17` 有规则，正式回传尚未接通 |
| 搜狐、企鹅、小红书、微博、快手、抖音 | 全部提供平台选项；典型格式见平台表；未识别的公开 URL 仍能经“其他”保存 | C `src/shared/accounts.ts:191,227,239,287` 只有部分平台目录；C `distribution-publication-url.ts:19` 对这些未实现粗校验；真实全格式未查 |
| 其他、未知平台或新链接形态 | 不要求某个特定平台；归“其他”，只存 HTTPS 公共链接，不自动请求/识别身份 | G `app/geo/content/backfill_channels.json:11` 已有 other 分类；v2 需独立实现 |
| 带图片/视频的文章 | 发文和素材准备留在多号通/平台；回传只有元数据和公开链接，不传正文、图片或视频文件 | C `src/main/distribution-report-host.ts:81` 原宿主是独立手工模式；S `SeoDistributionReport.vue:162` 原派稿素材缺口，本方案不经过派稿 |
| 平台不支持自动发布 | 允许人工发完后填回传表单；平台目录不宣称自动发布成功；不为接回传解除发布器保护 | C `src/shared/distribution-capabilities.ts:4`、`src/main/distribution-production-policy.ts:1` |
| 失败、风控、验证码、审核中、未知 | 保留细分结果；标题/平台/账号可填“未提供”，链接可空；不会生成已发布事实或覆盖先前成功 | S `app/seo_distribution_protocol.py:16` 有观察状态；C `DistributionReportPanel.tsx:21`；v2 不再要求任务 |
| 成功后又回报失败/风控 | 新事件保留；按同一次本机发布尝试分组显示，成功历史不降级；不触发重发 | S `app/seo_distribution_report.py:524` 旧 apply_events 状态边界；v2 需单独状态机 |
| 同一事件重放、断网重试、ACK 丢失 | 同 device+eventId 唯一；相同摘要返原 ACK，摘要不同 409；持久提交后 ACK，客户端精确核对再清队列 | S `app/seo_distribution_protocol.py:136`；C `src/main/distribution-report-host.ts:248`；v2 复用原则而非 v1 形状 |
| 同一链接多个事件/电脑回传 | 各原始事件保留，在个人收件箱提示重复；标注时以客户+模块+范围+规范 URL 排他，冲突不暴露另一客户/所有者详情 | S `app/models/seo.py:553` 旧只按稿件去重；G `app/geo/content/routes.py:8727` 旧只按渠道稿去重；需新增约束 |
| 顾问把记录标错客户 | 跨客户/跨模块统一“在原目标撤销，再选择新目标标注”；每步检查对应当前权限，失去旧权限需超管撤销。原始事件不改，修订留原因/前后归属 | S `app/security/seo_distribution_advisor.py:63` 提交前锁与范围复核；现有 v1 不支持改客户 |
| 撤销标注、重标 | 原子撤销当前外部记录投影，回到原所有者待标箱；不得撤销平台真实发布；被撤销引用的核验立即失效 | G `app/geo/content/distribution_report.py:591` 已把账号编辑限制到账本；客户撤销为新增 |
| 一个链接归 SEO 还是 GEO | 以顾问所选模块为准；只有一个已开通模块可以预选但仍确认；不从平台/标题/账号猜 | X `app/models/module_workspace.py:12` 模块独立开通；同一 URL 跨模块分别记录，不自动双记 |
| 已标客户、暂未补网站/项目 | 客户模块级“范围待补”记录；仅所有者（仍有客户权限）及超管可见，不显示给全部顾问；补范围后再进入对应范围列表 | S `app/security/seo_distribution_advisor.py:63`；G `distribution_report.py:442` 现有原生写均要求范围，v2 不造默认范围 |
| 无关联稿件 | 作为外部发布记录展示，稿件列“未关联”；不插入必填稿件外键的原生表、不造稿、不计已验收稿件 | S `app/models/seo.py:515`；G `app/models/geo_content.py:122` |
| 关联稿件与正文核验 | 当前授权/分配、同客户同模块同范围、有效审核与固定版本；v2 通用核验适配，绝不借公众号 native_snapshot；不能匹配就显示未通过/暂不可核验 | S `app/seo_distribution_verification.py:13,42`；G `app/geo/publication_monitor.py:18,77`；S `app/api/seo.py:6904`；G `routes.py:8690` |
| 稿件变更、审核撤回、链接被改 | 核验按标注修订号+稿件版本+URL 指纹绑定，提交前再核对；旧证据作废，不自动更新成新稿已发布 | S `seo_distribution_verification.py:29,85`；G `publication_monitor.py:18` |
| 未标注堆积、收件箱满 | 个人页显示数量、80% 提醒；1000 条未标/10 MiB 未标数据上限；满额拒绝新收件，不 ACK 丢弃，客户端保留；清理策略见下 | S `seo_distribution_report.py:49,470` 现有容量拒绝；v2 上限和清理新增 |
| 配对码泄露 | 10 分钟一次性、高熵、按 IP/码摘要限速；可立即作废未领码；已领则吊销该设备；不靠码猜客户权限 | S `seo_distribution_report.py:223,248,294`；G `distribution_routes.py:20` |
| 电脑丢失、客户端本地移除 | 网页吊销设备，下一请求即拒收；本地移除不等于服务端吊销，界面明说；不跨设备接续旧 outbox | S `app/api/seo_distribution_report.py` revoke 路由；G `distribution_routes.py:131`；C `DistributionReportPanel.tsx:105` |
| 顾问离职、停用、权限/分配变化 | 每次收件检查所有者仍在职且有通用回传使用资格；离职吊销全部设备；每次标注/查询再查实时目标权限；失权不删除旧事实，不把箱子自动转给继任者 | X `app/security/auth.py:316`；S `seo_distribution_report.py:93`；G `distribution_report.py:107` |
| 离职后未标结果处理 | 一期不提供所有者转交接口、不改owner、不用人工SQL。超管从全箱筛选离职所有者，逐条标到正确客户/范围；继任顾问按新授权看已标记录，不能看原未标箱 | X `app/security/auth.py:316` 人员停用；客户归属为本方案新增，不宣称已有交接功能 |
| 设备到期、领取响应丢失 | 凭据90天到期后停止新收件，界面提前7天提醒；一期无静默续期或轮换。吊销/到期不删本地队列；重配产生新device，不自动搬旧事件；需人工核对后重新确认未送达结果 | C `src/main/distribution-report-host.ts:197` unknown保护；S `app/seo_distribution_report.py:280` 旧90天有效期 |
| 设备时间错误/离线很久 | occurredAt仅作为操作人报告时间，允许历史离线结果；过于未来（超过服务端24小时）拒绝并提示校时。receivedAt由服务端生成，保留/排序/限速不信任设备时钟，重试不改已确认事件 | C `distribution-report-host.ts:205,220` 旧时钟限制；v2时间边界新增 |
| 超管、顾问、客户、普通账号 | 超管可全箱处理并留审计；顾问看自己未标箱及已授权/已分配范围外部记录；客户/普通账号不能看未标箱；不因知道 receiptId 就可读 | S `api/seo_distribution_report.py:100`、X `auth.py:90`，新权限矩阵见下 |
| 系统管理员JWT、账号设置编辑者、无客户授权顾问 | 系统管理员JWT按实时系统角色识别，不使用ctx.is_superadmin；普通settings.accounts编辑者、客户账号、API key均拒绝；在职顾问即使零客户grant也能用个人箱，标客户时才要求授权/开通 | X `app/security/auth.py:71,278`、`app/security/advisor_tenant_auth.py:36,88`；资格谓词见下，无新增许可开关 |
| 目标客户模块未开通/已过期、项目已取消分配 | 只拒绝本次标注，原始结果保留待标；提交前锁后重查模块status/expires、当前grant和assignment，不因设备已配对而授权客户写入 | X `app/models/module_workspace.py:12`；S `app/security/seo_distribution_advisor.py:63`；G `app/geo/content/distribution_report.py:107` |
| 同码被两台电脑同时领取 | owner及pending行按固定锁序重查；条件更新pending→active且未过期才可签发一次。仅一个提交成功；另一个统一PAIRING_CODE_UNAVAILABLE，不泄露领取人，不保存明文重发凭据 | S `app/seo_distribution_report.py:248` 原v1锁后消费可借鉴；v2需新增并发反例 |
| 页面缓存/切换用户/搜索导出 | 用户隔离缓存，页面切换清空旧数据；列表/详情/数量/检索/导出统一过滤；响应 no-store；不把配对码、设备凭据、私密 URL 参数写日志 | S `SeoDistributionReport.vue:17,25`；X `app/seo_main.py:598`；v2 需全接口覆盖 |
| 可读文案、不发邮件 | 用“收到/待标客户/人工报告/未核验”等分层文案；所有提醒只在页面和客户端；无邮件功能 | C `DistributionReportPanel.tsx:18,20,78`；邮件为任务硬约束，非已有能力推断 |

## 平台链接格式与粗校验（不作身份认定）

下表是 v2 **拟支持的解析规则**，不是线上现状，也不是各平台全部格式。已实现证据以固定代码为准；未查的真实格式必须在实施时用公开、无登录、合成或平台文档样例补齐反例。任何未匹配的新形态可以归“其他”记录，不会成为某个平台能否配对/回传的条件。

| 平台 | 精确 hostname 与典型路径（示意） | 规范化与状态 |
|---|---|---|
| 公众号 | `mp.weixin.qq.com/s/<opaque>`；或 `/s?__biz=…&mid=…&idx=…&sn=…` | 保留长链四个身份参数，不把不同文章合并；短链路径区分大小写。C `distribution-publication-url.ts:7` 已有基础 |
| 知乎 | `zhuanlan.zhihu.com/p/<数字>`；`www.zhihu.com/question/<数字>/answer/<数字>` | 专栏有 C:14 证据；回答路径在当前解析器未查到，拟新增；两种形态暂不互相合并 |
| 头条 | `www.toutiao.com/article/<数字>/`、`www.toutiao.com/i<数字>/`，同平台裸域仅显式列别名 | C:17 已有两种；同 ID 跨路径是否等价未查，初期保守不合并 |
| 搜狐 | `www.sohu.com/a/<文章ID>_<来源ID>` | 当前客户端无规则，真实边界未查；初期按 hostname 粗认、保留路径/非跟踪参数，不宣称发文能力 |
| 企鹅 | `new.qq.com/rain/a/<文章ID>`、`new.qq.com/omn/<日期>/<文章ID>.html` | 当前规则未查；`mp.qq.com` 是创作入口，不当公开文章。未识别腾讯内容域名先归其他 |
| 小红书 | `www.xiaohongshu.com/explore/<ID>`、`/discovery/item/<ID>`；短链 `xhslink.com/<opaque>` | 当前回传解析器未实现。`xsec_token` 等分享验证参数不入库、不回传；去掉后可访问性未知就标“待人工核对”，不展开短链，不认定长短链等价 |
| 微博 | `weibo.com/<用户数字ID>/<内容ID>`、`m.weibo.cn/detail/<ID>`、`/status/<ID>` | 当前解析器无规则，真实边界未查；不同域名/ID表示法不盲目合并，账号名不参与授权 |
| 快手 | `www.kuaishou.com/short-video/<ID>`；短链 `v.kuaishou.com/<opaque>` | 当前解析器无规则；不自动展开，不把创作者后台链接当作品链接 |
| 抖音 | `www.douyin.com/video/<数字>`、`/note/<数字>`；短链 `v.douyin.com/<opaque>` | 当前解析器无规则；短链能记录，最终目的地未核验则不能声称正文/视频已核验 |
| 其他 | 任意合法公共 HTTPS URL（页面地址；不接受 userinfo、非默认端口、IP字面值/本地域名/控制字符） | 只作外部记录；未知域名不自动抓取、不识别平台/身份。保留非跟踪业务参数，去已知秘密参数；可提示手工粘贴不含秘密的公开链接 |

域名必须解析后精确匹配，不用 `endswith('qq.com')` 之类宽泛规则，不认 `mp.weixin.qq.com.attacker.invalid`。已知平台选择与域名不符时提示“平台和链接不一致，改为其他或重新核对”，不能伪造平台已认证。所有文本按纯文本渲染，链接新页打开用 `noopener noreferrer`，不提供服务端任意 URL 代理。

## 统一入口与服务归属

推荐**一个界面、一个配对、一个接收端**，不让用户选 SEO/GEO。仓库部署说明明确共享数据库配置和认证表；两个进程/前端独立（X `deploy/README-GEO-INDEPENDENT.md:29` 附近；准确行号见证据摘录）。本次没读实际 env，没连接数据库，因此这是代码/运维文档层面的结论，线上是否有覆盖配置未查，不能称已经实测同库。

优先复用现有 `/api/v1/seo/` 路由转发，在 SEO 服务挂载独立 `/api/v1/seo/distribution/v2/inbox/...`，网页标题不叫“SEO 配对”。SEO 与 GEO 都放“多号通回传”入口，打开同一身份级页面；GEO 可复用公共组件，不复制配对逻辑。入口只依赖正常人员登录，不要求客户和 SEO 商业权限；GEO-only 顾问也能用。

这需要改身份白名单和前端门禁：新增与 `SESSION_ROUTES` 并列的 `match_inbox_identity_route(method,path)`，不是把含 `{uuid}` 的字面量塞进现有 frozenset。它只匹配下表固定字面路径及完整UUID模板（锚定完整路径，拒绝额外段、重复编码、尾斜线别名和额外选择器）。`enforce_advisor_request` 在要求 advisor_tenant、tenant_id、SEO商业模块之前识别这组路由：仅 `advisor_identity`/`aud=advisor-session` 会话通过后进入专门 `require_inbox_identity`；业务会话不回退成身份会话。没有任何客户grant的在职顾问也可操作自己的收件箱。人员超管沿用无scope_kind的正常人员JWT，经当前系统管理员角色重查后进入同一依赖，不要求冒充顾问身份；不把普通 `settings.accounts` 编辑者自动当作全箱超管。拒绝裸API key、客户账号及普通角色。所有身份写入仍由独立owner/角色/并发检查保护，只免除选择客户，不免除鉴权。`auth._required`和前端路由守卫同步增加这组精确路由，不能仍被旧SEO商业权限门禁拦截。**绝不能放行整个 `/seo/` 或 `/distribution/` 前缀，也不改变其他业务路由。**

以下身份路由统一前缀 `I=/api/v1/seo/distribution/v2/inbox`；每条都必须进入上述精确匹配器和专门依赖：

| 方法 | I之后的路径 | 作用与限制 |
|---|---|---|
| POST | `/pairings` | 备注可空；owner只取当前登录人 |
| POST | `/pairings/{uuid}/cancel` | 仅自己的未领码，超管可处理；带expectedRevision |
| GET | `/receipts`、`/receipts/count`、`/receipts/{uuid}` | 列表/数量/详情统一owner过滤；超管可显式筛选owner；不能让用户传owner越权 |
| GET | `/devices` | 只列自己的设备；超管可显式筛选 |
| POST | `/devices/{uuid}/revoke` | 当前owner或人员超管，expectedRevision；拒收后续事件 |
| POST | `/receipts/{uuid}/archive`、`/receipts/{uuid}/delete` | 仅未标/已撤销记录，owner或超管，expectedRevision；不能借此删除已标客户事实 |

身份页始终使用已有身份会话，不因进入GEO壳或当前已选客户而改用业务JWT；标注时才为目标模块选客户并取得原有业务会话。GEO入口只打开此页，公共收件API客户端固定使用SEO v2基址，不让GEO客户端惯例自动改成 `/api/v1/geo/...`。

资格完全由已有人员身份推导，不新增“通用回传资格”授权字段、env或业务模块条件。冻结谓词如下：`person = 已验证人员JWT且user_id非空、user.is_active且未锁定`；`inbox_admin = person且当前role.is_system且role.name=="管理员"`；`inbox_advisor = person且按现有顾问角色判定且scope_kind==advisor_identity且aud==advisor-session`。`require_inbox_identity`仅允许二者；`require_inbox_superadmin`仅允许inbox_admin。管理员JWT没有ctx.is_superadmin也必须可用；该字段在当前auth.py:71主要代表API key兜底，**不拿它作本功能超管判定**。API key即使原系统称超管也拒绝本功能，因为不能确定收件owner；非顾问且非系统管理员的settings.accounts编辑者和绑定客户的普通/品牌账号均拒绝，不借apply_advisor_claims的旧豁免扩大权限。顾问users.tenant_id可有历史默认客户，但个人箱不据此归客户。这里“超管”均指上述人员系统管理员；业务标注仍执行原目标模块的当前权限及tenant限制。

菜单门禁也作精确约定：仅当`match_inbox_identity_route`命中上述**人员身份**方法/路径时，`auth._required`返回`(None, method为写操作)`，None在现有auth.py:110明确表示不限菜单，绝不表示免登录；这些handler只依赖`require_inbox_identity`（内含require_auth和上述实时谓词），不叠加require_scoped_auth的SEO菜单门禁。`enforce_advisor_request`对命中且合格的advisor_identity早退在tenant/module检查之前；非法/业务JWT不早退。三个设备POST端点只走独立设备认证，claim仅验证一次性码；它们不进人员身份匹配器，不要求人员JWT也不接受JWT代替设备凭据。SEO/GEO的label/unlabel分别登记各自精确业务读写键（SEO seo.content、GEO geo.content），走各自现有写入门禁/当前客户授权/范围分配/提交前复查；**不**把整个v2前缀放进免菜单规则，不照抄v1整段路径规则。合成验收必须包含“GEO-only且零SEO菜单权限顾问成功出码/读自己的箱；settings.accounts普通编辑者/API key/客户账号失败；系统管理员JWT成功”。

标注/改标等业务写入放在各模块精确的新路由，使用该模块当前客户业务会话、已授权客户和网站/项目分配校验，并在提交前复核。设备令牌完全不能调用这些管理写入。跨模块由浏览器向目标服务提交，服务间不用设备令牌或用户凭据作转发，也不创建内部万能账号。GEO 直接读共享收件表，只写经授权的标注字段。

实施前应以不含连接串的部署配置证明目标服务确实同库/认证相容；若实际不同，停止假设共享表：需单独评估同域统一 API 与跨服务数据接入，当前工时和“无需部署变更”的结论不成立，不在本次暗加桥接服务。

## 数据、接口与权限最小边界

### 两张表及记录形态（建议，不执行 DDL）

`distribution_inbox_devices`：UUID、owner_user_id（users 外键，限制删除）、备注、状态 pending/active/revoked/expired、配对码摘要/过期时间/领取请求ID、设备凭据摘要/到期时间、创建时间、修订号和脱敏审计/有界限流JSON。待领设备行即配对码，无须第三张pairing表；码和凭据只返回一次，均不保存明文。设备凭据90天有效；一期只允许新码重配，不提供静默续期或轮换。设备表不设额外“启用才准单次发送”的隐藏门槛，单次reviewed=true即本人本次同意；自动上传发布史/无人上传不实现。更换所有者必须新码/新凭据，不直接改owner。

`distribution_inbox_receipts`：UUID、owner_user_id、device_id、event_id、attempt_id、内容摘要、接收时间、发生时间、platform（含other）、title、reported_account、result/reason_code、安全公开URL/canonical_url/url_hash/normalizer_version、可空tenant_id/module/scope_id、可空关联稿件ID及固定版本/摘要、当前标注状态/修订号、核验状态、人工账号覆盖值、修订历史JSON。原始上报字段和owner不可被顾问覆盖；顾问修改是并列标注。device+event_id唯一；attempt_id是本机一次发布尝试的随机UUID，只用于同owner+device分组，失败/风控事件不取代先前成功，不能凭该ID跨电脑/所有者关联。历史仅存目标ID、操作者ID、动作、修订号和时间，不存历史客户名/稿件标题；读取时按当下授权决定是否解析名称，无权限的旧目标和核验附件引用不返回。用户文本按纯文本显示，不插入HTML。

有效成功标注增加部分唯一索引 `(tenant_id, module, COALESCE(scope_id,0), url_hash)`，仅对 `label_state=active AND result=success AND url_hash IS NOT NULL` 生效，覆盖同客户同模块同范围的多电脑重复；scope=0 为“范围待补”独立范围。URL 哈希命中还须比对 canonical 字符串；极小概率碰撞时返回人工处理错误，不误合并。模糊短链不猜等价，可能保留两个待人工合并的候选。

审计记录操作者ID、时间、动作、旧/新目标ID、修订号、原因和核验引用，不存设备明文凭据、配对码、平台秘密参数或网页原始 HTML。账号名、标题、URL仅出现在按权限读取的业务记录，不出现在接入日志/错误异常中。两表的结构、索引及权限检查共用同一个契约版本，两服务不各自建不同结构。

### v2 最小接口契约

- 身份级：出码、作废未领码、个人收件箱列表/详情/数量、设备列表/吊销。所有者从登录身份确定；请求不能指定他人 owner 来出码或列箱。
- 设备级：固定 `POST I/device-pairings/claim`（pairingCode、requestId；一次领取与unknown保护）；固定 `POST I/device/results` 和 `POST I/device/ack`（后者只查自身eventId+digest的精确ACK，不列箱）。body为 `schema=2,eventId,attemptId,occurredAt,platform,title,reportedAccount,result,reasonCode,publicUrl,reviewed=true`；没有tenant/module/scope/task/grant/accountId字段；有这些越权字段则拒绝，不忽略。允许reportedAccount=null并显示“未提供”，失败时title亦可空。platform固定枚举 `wechat,zhihu,toutiao,sohu,qq,xiaohongshu,weibo,kuaishou,douyin,other`，客户端目录其他ID只经显式映射，不能把wechat-article/wechat-official混写进v2。结果固定success/failed/risk_control/verification_required/pending_review/unknown。
- 0.3.7新增独立v2 transport：固定现有HTTPS origin+上述SEO v2三个设备端点，精确method/path白名单、无任意URL、无重定向、不附浏览器Cookie/人员JWT；复用TLS/超时/响应体积和no-store保护。源码 `distribution-report-transport.ts:43` 当前白名单仅v1，必须明确新增另一实现，而非放宽成任意路径。独立加密凭据、SQLite/outbox、配对UUID和错误码；v1宿主及白名单原样保留。网页身份API和设备API权限不互用。设备令牌采用与v1格式不相容的v2类型前缀，服务端仅保存完整令牌摘要，拒绝人员JWT和v1令牌；网页身份路由不能拿设备令牌调用。
- 收件只写到凭据对应 owner 的待标箱。单次事件限 16 KiB；标题 300 码点、账号 60 码点、URL 2048 字符、允许的 reasonCode 枚举；删除控制字符、限制总大小，拒绝任意平台错误栈/HTML。成功必须有公开链接，其他结果可无；任何结果都不自动发布/重发。
- ACK至少精确回显 `schema,eventId,deviceId,payloadDigest,receiptId,receivedAt`。落库成功后才返回；鉴权及吊销检查通过后，先查device+eventId：同摘要重试直接返原ACK，不能因后来满额/改标/删除内容而失去已持久ACK；异内容409。只有新事件才占收件容量，容量检查/插入/计数同事务。内容清理留事件摘要和精确ACK墓碑，查询只回ACK，不泄露当前客户归属。不能把“业务标注失败”当收件失败重发平台文章。
- 标注由目标模块精确路由受理：`POST /api/v1/{seo|geo}/distribution/v2/receipts/{uuid}/label`，body为expectedRevision、targetTenant、可选范围/已审核稿件引用、备注。模块由路由固定，不允许body偷换。仅未标/已撤销记录可选新客户/模块；已标同客户的范围/账号/稿件修改走该路由并复核原新对象。撤销用 `POST /api/v1/{seo|geo}/distribution/v2/receipts/{uuid}/unlabel`，body仅expectedRevision、reason，必须匹配记录当前模块/客户及原目标当前权限。两条业务路由都增加本模块精确权限白名单，保留现有总写门禁与提交前复查，不进入身份路由免选客户名单。事务锁receipt，检查原所有者或超管、目标授权/分配/开通、范围与稿件归属、版本/审核，再写修订；唯一冲突只返回通用错误，不暴露另一所有者/客户。
- 第一期只允许原所有者或人员超管标注/改标；其他有同客户范围权限的顾问只读。跨客户/模块一律先在原目标unlabel再向新目标label，超管也相同；无跨模块直改接口、所有者转交接口或服务间HTTP代写。UI明确两步及当前状态，不承诺两步原子成功；第二步失败就安全留在待标箱。
- 在开发前冻结严格schema、重复JSON键拒绝、各字段空值/枚举、事件摘要序列化顺序和UTF-8规则、URL规范化版本及跨语言合成向量。客户端本次确认后生成不变事件并持久化；服务端按同一规则校验digest，不能靠各端默认JSON编码猜一致。业务改标/版本变化不更改原ACK摘要。

### 可见范围和操作矩阵

| 身份 | 未标箱 | 已标客户记录 | 标注/修改/撤销 | 设备 |
|---|---|---|---|---|
| 生成配对码的在职顾问 | 只看自己；即使无客户选择也可看 | 自己原始上报可看；客户归属详情仍须当前目标授权；其他人的只看自己已授权且已分配范围 | 只处理自己的，且目标已授权；涉及原目标也要有权限 | 只管自己的 |
| 人员超管 | 全部，可按所有者筛选 | 全部 | 可代标、纠错、撤销、离职结果归档；有审计，不转交owner | 可全部吊销 |
| 其他顾问 | 看不到他人未标原始数据、数量与搜索命中 | 仅当前已授权客户+已分配网站/项目；无范围记录不开放 | 第一期不改他人归属 | 看不到他人 |
| 客户/普通账号/裸API key | 不可见 | 新外部记录默认不进入客户视图，之后若开放需另审 | 无 | 无 |
| 配对设备 | 只能提交自己的事件和查自己的精确 ACK，无权列箱 | 不能读取标注后的客户、其他设备或稿件 | 无 | 不可自改 owner |

顾问原始字段所有权不能反过来成为获取未授权客户信息的依据。超管代标不把原所有者加入客户授权。列表、计数、详情、导出、搜索、核验附件和改标历史都用同一权限边界，历史上其他客户的名称/稿件不可泄露。

### 字段级可见性（所有handler共用同一投影器，不返回原始ORM/JSON）

| 接口/场景 | 可返回字段 | 必须剔除/固定响应 |
|---|---|---|
| 个人未标列表/详情/数量 | 仅自己的event元数据、安全URL、平台/标题/上报账号、结果、接收时间、当前revision；自己的重复URL候选 | 他人的owner、receipt、目标、URL、数量/搜索命中一律不可见；不存在与无权ID同为404 |
| owner查看自己已标事件但已失去目标权限 | 自己原始安全上报及“客户归属不可查看” | 当前/历史tenant/module/scope/稿件ID与名称、核验证据、操作者信息均不返回，不用原始所有权恢复客户读取权 |
| 已授权客户+已分配范围的其他顾问查看外部记录 | 当前授权范围内的标题、安全公开URL、平台、发布账号、操作人报告结果、稿件关联与当前可见核验摘要 | 不返回其他owner/device/eventId及原始payload；不返回旧客户/旧scope/旧稿件字段和他人的收件箱重复候选 |
| 修订历史（含list/detail/search/export及label/unlabel响应） | 对读者仍有对应目标权限的历史可解析该目标；无旧目标权限最多返回“曾修改归属”的opaque动作及时间 | 无权的旧目标ID/名称、稿件标题/ID、URL、核验附件引用和操作者身份一律不序列化。超管仍按人员角色实时复核 |
| 冲突/重复提示 | owner自己的未标重复提示可含自己的安全URL；授权业务重复仅固定“已有相同链接，请核对” | 409/唯一索引异常不带冲突行receiptId、另一owner、tenant、canonical URL或SQL异常；不能凭接口枚举跨客户记录 |
| 撤销/删除/归档/标注响应、核验附件 | 返回同一投影器当前允许字段；附件每次下载重查目标权限和revision | 不把修改前对象或旧附件直通返回；授权撤回、改标、撤销后旧下载URL失效 |
| 接入/错误/API审计日志 | 路由模板、固定错误码、必要人员ID/动作；详细业务修订只留受控业务审计 | v2日志中UUID路径替换成模板，不记receiptId、公链/URL参数、标题/账号、原始body、配对码/设备凭据。`api_audit_logs.endpoint`及operation_audit同步使用模板，不让中间件绕过脱敏 |

不合并展示未经授权的“有相同记录但你无权查看”等存在性提示。客户端和网页纯文本渲染标题/账号/备注，链接禁自动预览，打开使用noopener/noreferrer和不发送Referer；只展示已清洗的HTTPS公开地址。

### 改标、跨模块与并发

原始receipt主键和上报永不变，只有一个当前有效归属；每次标注、同客户修改或撤销各自在共享数据库单事务中完成，要求expectedRevision，一次只成功一个写者。跨客户/模块纠错是下述两步，不复制成另一客户新收件，避免旧客户残留可见副本。

同客户同模块内改范围由该模块执行原/新对象检查。跨客户或跨SEO/GEO的“改标”对所有人统一拆为原模块撤销、新模块重标两笔事务，使用各自客户业务会话及最新expectedRevision；不提供单次跨模块直改，不从SEO导入GEO运行时模块。第一步成功即撤掉旧目标可见性，第二步失败/取消仍是待标状态，原所有者/超管可以接着处理，不会同时归两个模块。失去旧目标权限时要求超管先撤销，不能借身份路由逃避客户权限。UI切换目标必须清旧会话/请求并拒绝迟到响应。

不对 v1 或已有原生 publication 做跟随撤销，不删真实发布事实。v2 外部记录列表直接查询当前 receipt，不维护可能脱节的客户副本；异步核验结果带 receiptRevision+URL+稿件摘要，旧任务结果在提交前失配即丢弃。共享两表的提交与审计同事务，客户端超时继续按 eventId 重试；不重发文章。

## 去重、链接安全与核验语义

去重分三层：①设备+eventId 防重放；②个人收件箱对同 owner+规范URL 提示重复，多个来源仍保留原始证据；③有效归属按客户+模块+网站/项目（或范围待补）+URL 唯一，不能多次计数。同 URL 可分别属于 SEO/GEO 或不同客户，但只在明确人工选择和各自权限内建立，不做跨客户自动归并，不展示其他客户的重复详情。

规范化：只接受 HTTPS，解析 hostname 小写/IDNA并匹配精确白名单，去 fragment、默认端口表示和已知跟踪参数；不降低路径大小写，不任意解码保留字符、不随意删业务 query，不把长短链、移动/桌面域名凭猜测合并。公众号四参数、百家号等文章身份参数必须保留。已知平台只去白名单跟踪参数；other 保留非秘密参数。遇到疑似凭据参数，客户端先去除或请人粘贴干净公开链接，服务端再次拦截，**原始含秘密输入也不保存进审计**。不读取任何本机平台登录信息。

域名粗校验只证明“地址长得像这个平台”。不得说明账号属于该顾问/客户；标题相同、HTTP 200、短链存在也不等于发布成功、正文一致或平台审核通过。不在接收/未标阶段抓页面，不自动展开短链。

可选关联稿件时，先检查本模块原有授权、分配、开通/有效期、稿件审核和固定版本；复用通用安全抓取与正文匹配组件，新增与 v2 receipt 关联的核验 intent，不调用只接受公众号任务的 v1 `native_snapshot`。SEO 的原正文+截图语义、GEO 的版本指纹与正文匹配不降低。若某平台抓取器未适配、验证码、只看见标题、视频没有可比正文，就显示“暂不可核验”，不能用弱匹配冒充通过。无关联稿件一律显示“未关联稿件，不核验正文”；有图片/视频的正文核验不证明图片/视频一致。

原生发布状态/服务任务/KPI不自动变更。以后若希望外部结果直接完成原稿件发布，必须另经原生最终门禁：SEO `complete_manual_publication_in_transaction`，GEO `_write_publication`，那是额外明确范围，不在本最简版本暗中加入。当前外部列表可以展示“操作人报告成功”，与原生已核验发布分列统计。

将来启用公共页面抓取时继续复用现有 SSRF 边界：解析公共 IP、屏蔽本地/私有/保留地址、每一跳重新验证、有限超时/响应体/跳转、不带 Cookie、不读取平台认证、不返回原始网页 HTML。未知域名与短链第一期只记录。上述是未来实施验收项，本次没有发起真实页面抓取或数据库查询。

## 堆积、停用与默认关闭

- 配对本身不受客户/渠道条件限制。新安装不自动收集或上传发布史；配对也不自动开启无人上传。人点“确认回传”就是本次明确同意；可选“为本配对记住结果回传提示”默认关闭，不影响配对或单次人工发送。
- v1 原客户/范围开关原样保留；v2 未标收件不是写客户。人工标注是一次客户归属操作，不自动开启该客户的 v1 派发/自动回传开关，也不放松原生稿件审核。任何后台自动客户归档保持关闭；如未来要自动归档另审，不增加本轮开关。
- 每所有者最多20个有效设备、20个未使用码；过期/撤销释放待领名额。设备60条/分钟、owner300条/小时：不新增Redis/env，统一在既有users的owner行锁下计数，设备有限时间桶放devices JSON；owner计数聚合其设备时间桶，收件容量按索引统计，收件/出码/清理均采用一致锁序并处理死锁重试，跨worker不能突破。数据库/计数失败整笔拒收，不ACK。已知配对码失败次数同样落pending设备行JSON，60秒10次，领取前锁后重查；随机码192位，不记录原码。未知码IP兜底仅用有界进程内失败桶，不宣称全局抗DDoS或新增网关配置；这项残余限制与v1相同，不能把它当作跨worker可靠限速。错误不泄露码存在性。
- 未标上限 1000 条或 10 MiB（先到者），80% 页面/客户端提示。达到上限 HTTP 429+明确错误码，**不 ACK、不静默丢失**，原 outbox 留待处理。单个故障配对不能阻塞其他配对。
- 未标 30 天显示“长期未标”；90 天移到仅 owner/超管可见的“已归档、未标客户”，仍受总存储限额约束，不靠改状态腾空无限容量。总保留最多 5000 条/50 MiB 每 owner，达到后停止接收并提示人工清理。
- archive只把未标/已撤销记录从默认列表移到“已归档”，不删除内容、不释放总容量；delete由owner/超管明确确认，清除该行标题/账号/URL等业务内容，但**不硬删收件行**：同一行保留owner/device/eventId/摘要/精确ACK/必要脱敏修订，转为墓碑至少180天，因而仍只需两表。180天前未标归档内容可在已有清理任务中按页面预告的固定策略同样转墓碑；到墓碑保留期结束且无有效设备/业务引用后才允许清行。已标业务记录不自动清除；清理不删客户事实，全部与收件采用一致锁序和revision校验；已持久ACK重试先查墓碑，不因已归档、已清内容或满额而重复落库。总上限包含仍保留的墓碑行，满额不能靠改状态无限绕过，必须提示超管处理保留期。
- 离职/人员停用：所有设备请求实时检查owner的is_active和当前角色，失效立即拒收；角色改变失去通用回传资格同样拒收。客户授权变化不改变未标数据所有权；有关客户的查看/编辑实时撤权。超管先吊销旧设备，再从全箱逐条代标到正确客户/范围；继任顾问凭自己当前客户授权查看已标记录。一期不转交未标owner，不提供批量transfer，不暗用人工SQL，也不转交设备凭据。
- 吊销以服务端为准，不靠客户端本地移除；泄露码可作废，泄露/遗失设备令牌则吊销设备，再用新码配对。吊销后的已确认本机结果保留，不能由另一所有者的新配对悄悄续传。

## 对已上线功能的影响与拟用文案

一键出码仍是一键；新入口不再“同时开启当前客户回传”，不创建连接。旧 v1 界面保留原有说明，仅对仍用旧任务的用户可见；默认主入口是通用回传，避免继续引导新用户走公众号专属链路。顾问公众号标注的已有数据保留，新字段名推广为“发布账号”，清除人工覆盖后回到设备上报值，不能改变原事件摘要。

拟用文案：

- 出码：“不用先选客户或平台。配对后，这台电脑确认回传的结果先进入你的待标客户列表。”
- 配对：“结果接收人：〔顾问显示名〕。这个配对不授予客户或稿件权限。”
- 提交：“我已核对本次发布结果。这里只回传记录，不会再次发文。”
- 成功收件：“已收到，待顾问标客户。操作人报告已发布，页面尚未核验。”
- 失败/风控：“已收到：平台风控。没有登记为发布成功。”
- 客户标注：“选择客户；需要时选择 SEO/GEO。网站或项目可以稍后补，稿件可不关联。”
- 未补范围：“已归客户，网站/项目待补。其他顾问暂时看不到这条记录。”
- 无稿件：“外部发布记录 · 未关联稿件，不核验正文，不计入稿件验收。”
- 异常：“平台和链接不一致，请重新核对，或改为‘其他’仅作记录。”
- 吊销：“停止接收这台电脑的后续回传。已收到的记录保留。”
- 改标/撤销：“只修改系统记录的客户归属，不会删除平台上的文章；原标注保留在操作记录中。”
- 容量：“待标记录已满，结果仍留在本机。请先标注或清理，再重新发送；不会重新发文。”
- 旧配对：“旧版稿件派发配对，仍按原客户和公众号工作。通用回传请升级 0.3.7 后另加配对。”

提醒只有站内和客户端提示，不发送邮件，不联系任何人。

## 代码证据与只读范围

固定SHA与文件哈希见 `plan/audit/source-manifest.json`；主正文 `sources.json` 共57份固定提交文件快照（包含历史/对照版本），全部与manifest哈希一致，复核见 `snapshot-integrity.json`。另有7份模型/部署文档 `supplement-sources.json` 和7份鉴权/路由补充 `routing-sources.json`。本轮直接复用，没有fetch/checkout/新建分支。GEO原基线ab3d732、#778 head9465572与合并e4d73c1对照保留，不把移动工作树当冻结证据。

| 编号 | 固定文件:行 | 结论 |
|---|---|---|
| S1 | S `app/seo_distribution_report.py:40,71,174,223,406` | 账本是客户模块 JSON；连接、配对、任务都仍依赖客户/网站/公众号 |
| S2 | S `app/models/seo.py:506,515,553` | 原生发布必填客户+稿件，原唯一约束不是收件箱链接去重 |
| S3 | S `app/seo_distribution_protocol.py:12,66,72,91,136` | 独立 v1 前缀、公众号 URL、默认关、严格事件和 ACK；v2 不能直接插字段 |
| S4 | S `app/api/seo.py:6904,9655`，`app/seo_distribution_verification.py:13,42` | 审核、事务完成、正文+截图核验；v2 必须保持证据含义 |
| G1 | G `app/models/geo_content.py:116` | 原生发布要求 variant，不能无稿直插 |
| G2 | G `app/geo/content/distribution_report.py:84,107,222,248,285,442,568` | 客户账本、实时顾问权限、公众号账号/占位、固定稿件、账号标注 |
| G3 | G `app/geo/content/routes.py:8690,8772`，`app/geo/publication_monitor.py:18,77` | 发布最终门禁和固定正文指纹核验 |
| C1 | C `src/main/distribution-report-host.ts:33,41,197,216,248` | 正式回传宿主只认公众号和已有任务；有领取不确定处理和严格协议 |
| C2 | C `src/renderer/src/DistributionReportPanel.tsx:25,78,80,100` | 公众号文案、模块选择与无派稿就无回传表单 |
| C3 | C `src/main/distribution-publication-url.ts:3`，`src/shared/distribution-capabilities.ts:4` | 其他用途的 URL 粗规则存在，但不能推断全部平台有可靠发布能力 |
| X1 | X `app/models/module_workspace.py:12`，`app/models/user.py:9` | 模块 JSON 绑定客户、用户无通用 JSON |
| X2 | X `deploy/README-GEO-INDEPENDENT.md`，两服务 unit | 文档说明共享数据库/认证但分开进程；真实线上覆盖配置未查 |
| X3 | X `app/security/auth.py:290,316,437`，`app/security/advisor_tenant_auth.py:15,88` | 当前人员实时鉴权和会话白名单；新无客户入口必须精确增加身份级通路 |

已读取旧一期设计、contract-changes、seo/geo/seo2/geo2/client2 结果与 vectors；这些历史方案里的公众号/派稿要求被本次 18:40/18:43 指示替换，兼容范围仍保留。本窗没有重新连接远端仓库或生产，只复用前序公开 REST 摘要；客户端公开 REST 先前返回 404，不登录追查。未跑仓库代码、数据库测试、真实发布或真实设备配对；本报告不声称端到端验收通过。

## 审查记录

各轮均为Cursor全新会话，`--mode ask --workspace ../seoC/src --output-format json`；不传resume，只在审查结束后为确认实际型号在同一会话取无工具的system/init元数据。提示词要求逐条对照源码、找遗漏/违背最简设计/公众号依赖/权限泄露/旧版兼容，列blocking及non-blocking；禁止修改源码、运行应用或测试、数据库/网络/真实账号/秘密访问。第3轮进一步要求coverage逐行列出，不接受抽样代替完整检查。

| 独立轮次 | 请求模型顺序及不可用情况 | 实际审查模型 | 结论/被审版本 |
|---|---|---|---|
| 1（18:58–19:01） | claude-opus-5-5-high → claude-sonnet-5-5-high → claude-sonnet-5-thinking-high 均exit1额度不足；随后composer-2.5 | Composer 2.5，同审查session的system/init确认 | FAIL，3 blocking、10 non-blocking；SHA256 ff95f286d9e1da075e32d61a37d08d410bd7c75a10998f799e5dd68eb9c11fef |
| 2（19:04–19:06） | 三个Claude别名再次按同顺序实试，均exit1额度不足；随后composer-2.5 | Composer 2.5，同审查session的system/init确认 | FAIL，3 blocking、7 non-blocking；SHA256 93e10456bbaed1130192f8ec7ee7307f438259fed7252fcf7c43d63319f73295 |
| 3（19:09–19:13） | 三个Claude别名再次按同顺序实试，均exit1额度不足；随后composer-2.5 | Composer 2.5，同审查session的system/init确认 | **PASS，blocking=[]，7 non-blocking；coverage逐条39行**；SHA256 edd3f319ccec910ec14b455ef5cb57276bd29b5b2ae9d912daf30071f11ee32c |

额度失败输出没有精确运行时型号，也没有完成审查，故仅记录请求别名、stderr的Opus/Sonnet额度错误及exit1，不伪造实际执行型号；没有调用GPT或auto。原始提示词/JSON/stderr/时间/退出码都保存在`plan/audit/roundN-*`；被审版本保存在`roundN-reviewed-plan.md`，verdict里的SHA256与其逐字节校验。`reviews-summary.json`统计独立session及型号确认。

第1轮发现与修订：

- B1：动态身份路由未落到具体中间件匹配机制。已补完整方法/路径表、UUID匹配器、身份会话早退、菜单/前端门禁边界。
- B2：超管跨模块直改承诺缺接口。已收敛为所有人统一在原目标撤销、再选新目标重标；无跨模块直写和所有者transfer，第二步失败留待标箱。离职结果由超管代标。
- B3：客户端v2传输未列固定路径白名单。已写固定SEO v2 origin/path、独立宿主/凭据/outbox，GEO网页也调用SEO身份API。
- NB1–NB10：保留同库/认证非秘密部署证明闸门；明确前端路径、DB行锁/时间桶与未知码限速残余、DHT2码长度熵和claim语义、90天到期重配、历史字段权限、平台枚举映射、attemptId分组、管理员JWT及不做owner转交。自查另修旧端升级提示不能新增、主快照为57份、满额后的原ACK恢复顺序。

第2轮发现与修订：

- B1：要求冻结系统管理员JWT/普通settings.accounts编辑者/客户账号/零客户grant顾问的资格判定。已加person/inbox_admin/inbox_advisor精确谓词；不用ctx.is_superadmin识别人员超管；不新增“通用回传资格”开关，API key拒绝。
- B2：要求明确SEO侧菜单检查及GEO业务路由。已冻结精确身份路由_required不限菜单但仍需人员鉴权、顾问身份早退、设备独立认证、SEO/GEO label/unlabel各自业务键与提交前检查，并列出GEO-only反例验收。
- B3：要求字段级ACL。已补个人箱/失权owner/同客户其他顾问/历史/冲突/附件/写响应/API审计逐项投影表；不返回原始JSON，不通过旧ID、冲突或日志泄露另一客户。
- NB及coverage：补迁移唯一revision归属与共享库就绪503闸门、同码竞争、模块未开通/到期、GEO壳身份API联调、archive与delete/ACK墓碑区别。GEO旧封装已有固定快照`frontend/src/api/geoDistributionReport.js:2,3`，并非缺证据；另读通用client确认baseURL为空，纠正前缀归因。删除采用同收件行保留墓碑，不新增第三表。

第3轮结论与后续非阻断事项：

- 第3轮全新session明确PASS、blocking=[]，确认前两轮身份路由、两步改标、客户端白名单、人员管理员/API key/字段ACL及迁移闸门均反映在当前正文，未发现与“无条件配对、独立回传、事后标客户、公众号仅一平台”矛盾的设计。coverage的39个scenario与场景表逐行一致。
- NB-R3-01：搜索/导出参数在开发前冻结，未实现前不暴露额外导出接口；所有列表/检索/导出同用owner过滤和字段投影器。
- NB-R3-02：SEO/GEO前端各使用专门inbox API模块，不注入tenant/project，不复用旧v1封装；合成联调按正文已有隔离要求验收。
- NB-R3-03：继续保留同库/同认证的非秘密部署证明闸门。真实不一致时实施阻塞并重估，不能暗加桥接。
- NB-R3-04：平台ID映射、normalizer_version和正反例向量属于开发前冻结契约；未查的真实平台全格式不宣称已支持。
- NB-R3-05：未知码IP失败桶仍是进程内兜底，跨worker不保证全局限速；不新增Redis、网关配置或env，不把此残余当全局防护。
- NB-R3-06：零客户grant顾问可以先收件，不能标客户；可提示“你还没有可标注的客户，请由超管按授权处理”，不因此阻止配对。
- NB-R3-07：契约冻结时逐条列身份GET→(None,false)、身份POST→(None,true)，None仅免菜单、专门人员依赖照常；设备认证和label/unlabel业务门禁不在这张免菜单表内。正文已规定匹配器及中间件早退位置，开发需用GEO-only反例确认。

三轮实际模型均由各自审查session的system/init确认是Composer 2.5；三个审查session互不相同，被审副本SHA256逐字节核验。第三轮通过后，终稿只更新本页状态和本审查记录，正文方案不再改变；见`plan/audit/delivery-verification.json`的一致性检查。PASS指只读设计评估无剩余阻断，不是代码、迁移或真实端到端验收。

真实部署配置、各平台全格式和真实账号发布均未查/未验，保留实施条件。本次未运行应用/数据库测试、未读秘密、未改仓库/分支/远端/生产，未登录真实账号、不发送邮件、不联系任何人。

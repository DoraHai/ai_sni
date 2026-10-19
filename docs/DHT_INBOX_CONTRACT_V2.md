# DHT v2 契约 · 2026-10-19 冻结 v2.0

权威顺序：RULES、SCOPE、各线 task、本文、原方案。配对码按 seoV2 task 使用 `DHT2-`，替换原方案的冒号；旧 v1 不变。SEO 接收，GEO 只复用共享表并执行自身业务授权。不做导出、域名粗检、平台路径规则、80% 预警、邮件、自动抓取或自动确认原生发布。

## 传输与形状

I=`/api/v1/seo/distribution/v2/inbox`，使用既有 HTTPS origin，同源人员身份 API 与 native 设备 API 分离。所有响应 Cache-Control:no-store。JSON UTF-8，拒绝 BOM、重复键、NaN/Infinity、额外字段、错误类型和孤立 surrogate。整数不接受 bool。UUID 为小写标准 8-4-4-4-12。正文 <=16384 字节；禁止设备请求 Cookie、Origin、Sec-Fetch-*、query、API key。只支持下列三个设备 POST，禁止重定向；不接受人员 JWT/v1 凭据代替设备认证。

所有时间均 UTC ISO `YYYY-MM-DDTHH:mm:ss.sssZ`。occurredAt 允许历史时间，首次新事件超过服务器未来24小时拒绝；已持久重放先恢复 ACK，不重新拒绝历史时间。

## 配对/设备

POST I/pairings：`{}` 或 `{label:string|null}`，label <=80码点，空则自动电脑名。owner 只取人员身份，不能提交 tenant/module/channel/account。返回201 `{schema:2,pairingId,pairingCode,expiresAt,revision:0}`。CSPRNG 24字节 base64url 无padding，码正则 `^DHT2-[A-Za-z0-9_-]{32}$`，37字符，10分钟一次性；仅保存 SHA256 摘要。显示前提示“此码需要多号通0.3.7，旧版请先升级”。

POST I/device-pairings/claim：`{pairingCode,requestId}`，requestId 为 UUID。返回200 `{schema:2,deviceId,credential,credentialExpiresAt,owner:{displayName},automaticSubmit:false}`。设备凭据 `dht2_<deviceUUID>.<43个base64url字符>`（32随机字节），只返回一次，仅存完整摘要，90天有效。owner姓名只有合法码成功领取时返回，不返回客户。单次 reviewed=true 即人工同意，不需开启开关。

同码并发仅一次成功；同 requestId 也不重新发凭据。响应丢失/unknown 不自动重领，网页吊销后用新码；独立 v2凭据/outbox，不接续其他设备/所有者/v1事件。停用/过期/owner离职锁定或角色失格，下一请求拒绝，包括 ACK 查询。不做静默续期、owner转交。

每owner最多20 active（未到期）设备、20 pending（未过期）码。沿用v1已知码持久限速（60秒10次），未知码IP/码摘要/全局有界进程内兜底（30/10/3000每分钟），不宣称跨worker全局IP防护，不加env/Redis。设备60新事件/分钟，owner300新事件/小时，服务器时间，owner行锁与devices有界时间桶跨worker串行；已持久重放不占额度。

## 事件与摘要

POST I/device/results，Authorization: Bearer <v2 credential>。单事件（不批量），必填且只允许下列12键：

`{schema:2,eventId,attemptId,occurredAt,platform,title,reportedAccount,result,reasonCode,publicUrl,reviewed:true,payloadDigest}`

eventId/attemptId UUID；每次人工确认产生新eventId，不可变；同一次本机发布尝试共用attemptId，仅同owner+device分组，不降级此前成功。

platform 任意非空文本 <=60码点，去Unicode控制字符后原样存储；显示类别由精确目录 `wechat,zhihu,toutiao,sohu,qq,xiaohongshu,weibo,kuaishou,douyin,other` 映射，其余为other，但原platform保留。title 字符串或null，<=300码点，账号字符串或null <=60码点。成功 title 可空（显示“未提供”），成功必须有publicUrl；其他结果可无URL。result 枚举 `success,failed,risk_control,verification_required,pending_review,unknown`。reasonCode 为null或 `platform_rejected,network_error,risk_control,verification_required,pending_review,unknown`，不接收错误栈/HTML。文本按纯文本展示。

publicUrl 为null或<=2048字符的可解析 http/https 绝对URL，有host，无userinfo，无控制字符/空白；不限制域名、路径、IP、端口，不进行抓取/展开/平台匹配。仅去fragment、host小写得到canonical_url（simple-v1），其余大小写/路径/query/默认端口均保留；不做URL跨平台等价猜测。存储清洗后公开链接，用户不得提交认证信息。

payloadDigest=小写 SHA256 hex，输入为下面固定位置数组的紧凑 JSON UTF-8（无空格、无ASCII转义、不转义 `/`，采用JSON.stringify字符串转义，无Unicode正规化；在任何清洗/URL规范化**之前**计算）：

`[2,eventId,attemptId,occurredAt,platform,title,reportedAccount,result,reasonCode,publicUrl,true]`

数组可避免对象键顺序和JS/Python排序差异。摘要包括原样platform和URL，清洗不改摘要/ACK。数字只有schema=2；时间是字符串，不能由各端重格式化已确认事件。vectors-v2.json含精确canonicalJson与摘要，合成数据，无真实身份。

ACK 200为**直接对象** `{schema:2,eventId,deviceId,payloadDigest,receiptId,receivedAt}`，receivedAt服务器生成。提交事务后才能返回；客户端精确核对全部关联字段后清outbox。

POST I/device/ack：`{schema:2,eventId,payloadDigest}`，返回相同精确ACK，尚未收到404 EVENT_NOT_FOUND；不列箱、不返回标注信息。同device+eventId唯一；相同摘要返原ACK，不同摘要409 EVENT_DIGEST_CONFLICT。鉴权/吊销检查→查重放/墓碑→首次事件验证/限流/容量→落库提交→ACK。满额、已标、已删不破坏原ACK。

## 身份权限与接口

person=已验证人员JWT、user_id存在、当前active且未锁定。admin=当前role.is_system且name=管理员；不能用ctx.is_superadmin/API key/settings.accounts编辑权冒充。advisor=现有顾问角色+advisor_identity+aud=advisor-session。身份业务JWT不回退成身份会话；客户账号/普通角色拒绝。零grant/GEO-only顾问可配对/读自己箱，无目标授权不能标注。界面：“暂无可标注的客户，请联系超管授权”。

精确路径/完整UUID匹配，无额外段/编码别名/尾斜线/selector。下表各行 `_required` 返回None仅免菜单，仍依赖require_inbox_identity：

| 方法 | I后缀 | _required |
|---|---|---|
| POST | /pairings | (None,true) |
| POST | /pairings/{uuid}/cancel | (None,true) |
| GET | /receipts | (None,false) |
| GET | /receipts/count | (None,false) |
| GET | /receipts/{uuid} | (None,false) |
| GET | /devices | (None,false) |
| GET | /targets | (None,false) |
| POST | /devices/{uuid}/revoke | (None,true) |
| POST | /receipts/{uuid}/archive | (None,true) |
| POST | /receipts/{uuid}/delete | (None,true) |

取消/停用/归档/删除body=`{expectedRevision}`（非负整数），返回 `{schema:2,id,revision,state}`；不返回旧对象。archive/delete只允许未标/已撤销。delete清业务内容，保留原ACK墓碑至少180天；不删已标事实。清理/标注/收件锁序统一：owner User→device（有时）→receipt；涉及角色/grant/module/scope时复核并锁当前行，提交前复查。

GET receipts query：state=`pending|active|archived`，默认pending；limit1..100默认50，offset0..5000默认0，q可选<=100；超管额外ownerUserId正整数，不传则默认自己的箱；顾问提交此selector拒绝。count沿用同state/q/owner过滤（不接limit/offset），返回 `{schema:2,count,unlabeledCount,unlabeledBytes}`。list=`{schema:2,items,total}`；详情是投影单对象；devices=`{schema:2,items}`，每项{id,label,state,revision,createdAt,expiresAt}。设备/列表不返回摘要、码、令牌、限流桶。无导出接口。

receipt个人投影：`{id,revision,state,platform,platformKind,title,publicUrl,reportedAccount,result,reasonCode,occurredAt,receivedAt,attemptId,duplicate,assignment,verificationStatus}`。assignment无归属为null，已失去目标权限为 `{hidden:true}`，有权限为 `{tenantId,module,scopeId,articleId,articleVersion,publishedAccount}`。history只输出动作/时间，旧无权目标不序列化ID/名称/操作者；不返回原始JSON。别人未标ID与不存在同404，数量搜索同一owner过滤。

## 业务标注与发布记录

POST `/api/v1/{seo|geo}/distribution/v2/receipts/{uuid}/label?tenant_id=<targetTenant>`，使用目标模块既有业务JWT/写门禁（SEO seo.content；GEO geo.content），不在身份免菜单表。

body严格 `{expectedRevision,targetTenant,scopeId?,articleId?,articleVersion?,articleDigest?,publishedAccount?,reason?}`。module由路由固定。scopeId/articleId正整数或null；articleVersion正整数/摘要小写hex64或null，稿件引用必须全部有效且同客户同范围、当前审核通过固定版本。scope可空不造默认范围；无scope仅owner（仍有客户权）与超管可见。publishedAccount字符串<=60或null（null恢复设备上报）；reason字符串<=200或null。原始上报与owner不改。

POST同前缀 `/unlabel?tenant_id=<currentTenant>`，body=`{expectedRevision,reason}`。只能owner或人员admin操作，复核当前客户/模块/原新范围授权及分配、模块active/trial和有效期；顾问仍受原有总写开关。已标跨客户/模块直接label拒409 CROSS_TARGET_REQUIRES_UNLABEL；超管亦先撤再标；第二步失败留pending。并发锁行+expectedRevision，失配409 REVISION_CONFLICT。

label/unlabel返回同投影器的对象，修订++并留脱敏历史。有效success按tenant+module+COALESCE(scope,0)+url_hash部分唯一，冲突409 DUPLICATE_LINK固定中文，不透露另一行/owner/客户；hash撞canonical不同时固定人工处理错误。各原始事件保留。

GET `/api/v1/{seo|geo}/distribution/v2/publications?tenant_id=...&scope_id=...`（scope可空），同模块读门禁和实时授权/分配，仅active投影。别人仅已分配非空scope可见；不返回owner/device/eventId/历史/其他客户信息。返回 `{schema:2,items,total}`，项含source=`external_report`和“外部回传”，不插原生必填稿件表、不改原生状态/KPI。收到、操作人报告success、正文核验分开。无稿件=unlinked；有稿件未适配安全正文核验=unavailable，不声称verified；任何核验绑定receiptRevision+URLhash+固定稿件版本并在撤销/改标后失效。

## 容量/失败

owner未标（含archived未标）1000行/10MiB硬上限；总保留5000行/50MiB含墓碑，达到拒新回传，不ACK、不丢本机队列。每事件存储成本按原始请求字节数计。archive不释放；delete只释放内容字节、不释放墓碑行；标注释放未标容量但不释放总容量。无80%提醒。90天未标归档不绕过容量；内容清理保留ACK墓碑。

统一HTTP错误 `{detail:{code,message}}`，固定中文无body/SQL/令牌回显：

| HTTP | code | message |
|---|---|---|
| 422/413 | INVALID_SHAPE | 回传格式不正确，请核对后重试 |
| 422 | INVALID_PUBLIC_URL | 请填写有效的 http/https 公开链接 |
| 422 | CLOCK_SKEW | 电脑时间超前，请校准时间后重新确认 |
| 422 | PAYLOAD_DIGEST_INVALID | 回传摘要不一致，请保留本机结果 |
| 401 | DEVICE_CREDENTIAL_INVALID | 设备配对已失效，请重新配对 |
| 403 | INBOX_FORBIDDEN | 当前身份无权操作此记录 |
| 404 | RECEIPT_NOT_FOUND/EVENT_NOT_FOUND | 记录不存在或无权查看 |
| 409 | PAIRING_CODE_UNAVAILABLE | 配对码不可用，请生成新码 |
| 409 | EVENT_DIGEST_CONFLICT | 同一事件内容不一致，请保留本机结果并核对 |
| 409 | REVISION_CONFLICT | 记录已更新，请刷新后重试 |
| 409 | CROSS_TARGET_REQUIRES_UNLABEL | 请先在原客户撤销标注，再选择新客户或模块 |
| 409 | DUPLICATE_LINK | 已有相同链接，请核对 |
| 429 | INBOX_CAPACITY_EXCEEDED | 待标记录已满，结果仍留在本机，请先标注或清理再重试 |
| 429 | RATE_LIMITED/DEVICE_LIMIT_REACHED | 操作过于频繁或设备数量已满，请稍后重试 |
| 503 | INBOX_SCHEMA_NOT_READY | 功能尚未准备好 |

两表缺失统一503，仅v2，绝不自动建表/迁移/扩权。详细日志路径UUID模板化，不记body/公链/标题/账号/码/凭据；API审计与operation_audit同步脱敏。

## 变更记录

- 2026-10-19 v2.0 冻结；DHT2-遵循seoV2 task，SCOPE覆盖原方案域名粗检/80%预警，事件摘要采用固定数组。通知在progress中向geoV2/clientV2发布。
- 2026-10-19 v2.0 勘误：事件键数量文字13更正12，字段列表和vectors未变。
- 2026-10-19 v2.0.1 修复向量生成时PowerShell文本管道将中文/emoji替换问号的问题：改UTF-8源码文件直接Node生成，向量中文和emoji及相应摘要更新；线协议/摘要算法/字段不变。下游须重新同步vectors-v2.json，新增断言禁止中文样例退化成问号。

- 2026-10-19 v2.0.2 第二阶段：新增精确身份 GET I/targets，无query，返回 {schema:2,items:[{tenantId,name,modules,scopes:[{id,name,module,articles:[{id,title,version,digest}]}]}],owners:[{id,displayName,active}],inboxAdmin}。items仅当前grant/有效模块/已分配范围；owners仅人员管理员可得。SEO可选稿件清单仅当前确认通过版本，GEO业务写与可选稿件由GEO服务最终复核；个人assignment增加articleDigest供同目标修改保持固定引用。新增409 URL_HASH_COLLISION「链接标识冲突，请联系超管核对」。设备三接口/摘要/ACK/旧v1不变。通知geoV2/clientV2以此版本更新独立API；客户端设备协议无需改动。
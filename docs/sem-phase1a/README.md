# SEM 阶段1a第六刀（task15）

仅实现本刀三项，完整阶段1a仍未完成；Draft叠slice5，不可合并或部署。现有工作台新增「首次接入 → SEM 影子规划」与系统设置下的账户授权管理，五种页面按定稿布局复用现有橙色主题、Vue/Element Plus/session/client。六个前端路由包括详情与导出；来源提交使用原#823完整契约（链接、长文本、可选PNG/JPEG/WebP、10MiB/张/10张/30MiB合计），不抓页/OCR/模型。保存来源201后可单独创建影子规划，并核对来源理由生成内部建议。真实预算帽/既有资产未核验，P5/P6继续阻断；导出仅内部Excel且有审计，客户只读不可导出。未授权/版本冲突/存储503显示明确错误，不假装成功。

为真实列表新增GET /api/v1/sem/phase1a/shadow/accounts/{account_id}/plans?tenant_id=...&offset=0&limit=50（上限100），生产principal每请求重核后check_scope(write=False)，数据库按payload精确tenant/account过滤。响应只有plan_id/version/product_line_id/pages/validation/execution_enabled六项元数据；索引并不证明来源有效，详情/Excel仍逐次复核来源hash/新版本/附件字节。全局管理员管理账户授权仍走require_admin及同事务DB重核，不获得来源/规划读取权。实际main端点矩阵扩为16×29，原未列执行路径继续关闭。

共享鉴权唯一必要变化：app/security/advisor_request.py的SEM_SHADOW_READ增加精确的phase1a/shadow/accounts/[0-9]+/plans GET。原因是#823没有列表端点；影响仅该账户索引读取，仍经模块与ProductionPrincipalAdapter检查。SEM_SHADOW_WRITE、管理路径、JWT及其他既有顾问写门禁不变。前端shadow路由需登录，菜单让已识别顾问可见；所有账户权限仍由服务端决定，不新增角色或功能开关。

附件新增app/sem_phase0/oss_attachments.py的OSSPrivateAttachmentStore，显式注入预配置SDK bucket，无SDK导入/环境读取/凭据值/网络初始化/应用装配。建议配置名SEM_ATTACHMENT_OSS_BUCKET/ENDPOINT/REGION/ROLE_ARN等仅为外部构造契约；不写app/config.py、不新增环境变量默认值。put_object强制x-oss-forbid-overwrite=true、private、SSE-OSS(AES256)，不先HEAD后覆盖；精确保留sem-sources/{tenant}/{account}/{page}/{revision}/{ordinal}-{sha256}。写前验证键/字节SHA-256，条件冲突或响应丢失则限量回读，长度/hash一致才幂等成功；其他冲突失败。读流分块限量并关闭，固定脱敏错误。仅连接/限流/临时错误可重试，最多3次，0.3/1秒退避；建议连接3秒/I-O10秒/单对象20秒/批次60秒/请求90秒为常量。SDK socket超时不等于绝对期限：上线装配必须另审SDK版本、经deadline约束的transport/worker及整批期限；本刀没有生产装配或云端验收，不能据此上线。ProductionServices默认attachments=None仍503。

授权撤销在既有账户锁及事务内，未写revoked_at/审计前检查：撤后无未撤销绑定409/LAST_GRANT_PROTECTED；剩余绑定没有有效可写顾问409/LAST_WRITABLE_ADVISOR_PROTECTED。顾问须用户启用且未锁定、当前角色符合现有is_advisor、精确顾问grant代次有效、默认客户grant存在。仅客户只读绑定不算保留可写顾问。两错误均绑定/审计快照不变；并发撤销串行后最多一条成功。幂等撤销保留；空账户GRANT_ACCOUNT_NOT_INITIALIZED不变。此保护仅覆盖本服务revoke，角色停用、其他grant撤销、模块/账户变化仍可能使顾问失去可用性，需独立生命周期治理，不声称全局永不失去顾问。

界面末条禁用按六字段管理响应统计未撤销行；最后可写顾问由后端实时判断并返回可读提示，不向前端泄露额外用户资料。变更成功后列表刷新失败保留旧记录、提示已保存但列表过期并暂停操作，人工刷新成功后恢复；上下文切换丢弃旧响应。

测试使用原TEMP受保护启动器，禁止真实.env和网络；内存OSS SDK stub仅测试。覆盖幂等/冲突/错误hash/路径/限量读/临时重试/权限不重试/并发同键/单图与多图部分失败数据库回滚（允许留不可达孤儿）；实际main既有显式内存附件201链继续通过。SQLite与现有CI临时PG测末条、只读剩余、停用/锁定/角色/顾问grant/默认客户失效、双撤销以及零副作用。前端无新依赖：六路由×三角色的真实SFC SSR、表单按钮、图片边界、错误/API/时区和授权刷新失败回归纳入npm run build，CI配置不变。最终计数、Cursor限制、CI及OSS证据见外部PHASE1A_SLICE6_HANDOFF.md和status15.md。

上线另批：真开私有桶/地域/RAM/ACL/密钥管理/SDK与绝对deadline装配、真实配置变量、请求体/锁等待/并发压测、备份恢复、初始化书面名单/脚本/PG迁移窗口与最小权限、孤儿对账/清理与生命周期/留存机制、真实预算帽与资产核验。无新迁移、sem_runtime扩权、触发器绕过或生产操作。无百度同步/OAuth、CI/.github、app/config.py、JWT、execute/upload-to-baidu/enable/customer-confirm/auto-pause变化。不合并/部署/force-push，不联系任何人或请求reviewer/assignee。

以下第五刀及更早记录均为历史，末条可撤与无前端描述已被本节取代。

---

# SEM阶段1a第五刀：生产来源持久化与正式影子入口

仅task12/slice5，完整阶段1a仍未完成；不可执行、不可上线。本刀已在app/main.py注册来源、影子规划及账户授权管理15个后端端点。无前端入口、无新环境变量或配置开关、未部署。新授权表为空时包括两类管理员全部403；未登录401。下面第四/三/二刀内容为历史，以本节为当前口径。

开发时间：status12步骤1起至本刀测试、提交、CI与OSS封存；不含人工审查、生产操作或影子观察。最终提交/PR/CI与测试数见外部PHASE1A_SLICE5_HANDOFF.md、status12.md。

## 来源与附件

`SubmissionRepository`为可替换接口；原`SubmissionStore(Path)`保留本机SQLite演练语义。新增`SQLAlchemySubmissionStore(connection_factory, attachments=None)`，无engine/URL/config/DDL/本地文件回退。生产`ProductionServices`只使用现有app.database的异步engine，通过run_sync把每次来源/影子操作（包括全部来源重核和规划/审计/预览提交）包在一个数据库事务中；不创建第二个生产engine。独立适配器亦可注入Engine.begin。提交锁账户以串行首次版本，再锁页面；expected_revision CAS，只追加新版本，产品线/URL/page身份不变。读取重核完整契约、租户/账户/page/revision、规范JSON SHA-256、页面身份、附件清单SHA-256及已配置后端的每个附件字节hash；阶段1a仍重核来源hash并拒绝任一更新来源版本。

仅新增`0079_sem_phase0_sources`接原唯一head0078：`sem_phase0_pages`、`sem_phase0_submissions`、`sem_phase0_attachments`。页面(account_id,tenant_id)复合FK引用账户；版本复合FK引用页面，附件复合FK引用版本，不能跨租户/账户/页面。三表有UPDATE/DELETE拒绝触发器，保留证据；版本/附件序号CHECK及PK/唯一索引。PG复用0078账户复合唯一索引，SQLite仅新增等价索引。旧迁移不变、downgrade拒绝、无GRANT或sem_runtime权限扩张。只在本机临时空库及现有CI临时PG随机schema验证，无生产迁移。

仓库未发现已有私有对象存储抽象或配置，因此提供显式`PrivateAttachmentStore.put_if_absent/read`接口，生产装配默认None；附件上传返回固定503/ATTACHMENT_STORAGE_UNAVAILABLE，不写本地磁盘充当生产附件后端。二进制仅PNG/JPEG/WebP魔数白名单，10MiB/个、30MiB/页、10个，跨页拒绝，记录原字节SHA-256、大小、MIME及signature_only_untrusted；不解码、解析执行或OCR，魔数不代表图片语义安全。私有不可变对象key按tenant/account/page/revision/ordinal/hash限定，不使用上传文件名，不向API返回key/原字节/原异常。提交时先私有写入并回读hash再写版本/附件元数据；后端失败数据库回滚。对象存储与PG无分布式事务，DB失败可留不可达孤儿对象，禁止本刀自动删除；上线前另定留存/孤儿清理策略。读取带附件的版本在后端不可用时同样关闭，不悄悄忽略附件。

## 正式入口与可见性

管理面鉴权例外（task12/review17）：账户授权三个端点有意使用真实require_admin→require_auth，再由AccountGrantService在事务内重核DB管理员、账户租户、SEM模块与生产初始化门禁；不走账户绑定ProductionPrincipalAdapter。平台管理员无需拥有顾问/客户账户绑定，不能把管理权限变成来源/影子访问权。来源/影子全部继续使用生产principal。真实main回归检查三个管理路由的依赖图、两类无个人账户绑定管理员仅管理端点200、DB角色变更三个管理端点403且绑定/审计不变。不能为字面对齐而给全局管理员强加顾问账户principal。

`app/main.py`仅装配三组router，保留enforce_production_secrets。来源与影子路由走真实require_auth→ProductionPrincipalAdapter→DB当前角色/tenant grant代次/模块/精确账户绑定，每请求重查，客户只读JSON/来源/到期建议；内部Excel GET会写审计，仍需顾问写权限。管理走真实require_admin→AccountGrantService事务内DB管理员角色重核，非可归属用户的API Key超管拒绝。顾问门禁`advisor_request`仅增加精确方法/路径列表，未列路径及其他既有写路由保持关闭；来源multipart身份/账户在服务层再核。不改共享JWT机制、百度同步/OAuth或前端。

生产管理装配要求该账户已有至少一个未撤销精确绑定，否则GRANT_ACCOUNT_NOT_INITIALIZED/403，包括首次授权。此策略使空新表对所有人403；首次账户初始化、最后一个绑定撤销后的恢复，仅能通过另行批准的数据库/运维初始化脚本写入首条绑定，不能靠超管POST或其他HTTP端点自行开门。上线前须在staging演练空账户拒绝、批准脚本初始化、HTTP管理、最后绑定撤销后拒绝及批准脚本恢复，核对租户/账户归属、用户角色、顾问grant代次、最小权限和审计；本刀不提供或执行初始化脚本、不连接staging/生产。本刀没有初始化/回填任何授权数据。已有工厂未启用该生产约束的隔离单元回归仅测管理服务本身；slice5另在真实main.app验证无种子首绑和最后绑定撤销后的三个管理操作，两类管理员均固定403/GRANT_ACCOUNT_NOT_INITIALIZED，绑定与审计全表快照不变。管理list响应只投影user_id、tenant_id、account_id、advisor_grant_id、generation、revoked_at，不返回用户资料或输入原文。

生产规划只使用持久化顾问提交的`product:/benefit:/keywords:`内容和明确预算/投放边界；缺项返回固定契约错误，不调用页面、OCR或模型，不使用合成HTML/假OCR或合成账户资料冒充线上来源。fixture_id在生产被忽略；合成演练适配保留原行为。尚无真实资产及账户预算帽核验，生产视图明确P5 existing_assets_unverified、P6 account_cap_unverified阻断；不能把声明预算当真实账户帽，演练逐项审批因此仍会拒绝。此刀不补真实同步。所有响应execution/go_live均false，正式客户确认pending，无新增execute/upload-to-baidu/enable/customer-confirm/auto-pause出口，内部XLSX仅演练。

## 验证与上线前事项

review17补充：独立测试进程仅在导入实际main.app时给ProductionServices注入实现PrivateAttachmentStore协议的纯内存测试后端，不替换真实auth/principal/服务，不改变生产默认None、不新增环境开关。HTTP上传201、GET200与原字节SHA-256相同、客户只读、跨租户/未绑定账户403且后端无新增访问、篡改422/SOURCE_INVALID、后端读失败503均有回归；该样例证明挂载组合成功路径，不代表实际云后端已装配或ACL/超时已验收。inventory固定为15端点数量哨兵，另有逐路由匹配及15×29端点矩阵；默认附件503、来源201使旧规划409和关闭路径均输出端点状态并显式断言。

上线顺序检查（须另外批准执行）：先在目标PG同版本的临时小库演练0077→0078→0079及EXECUTE FUNCTION兼容性；批准0078脏绑定只读巡检、清理责任与复合唯一索引扫描/锁窗口后，按窗口安装0078并核实(id,tenant_id)唯一键，再安装依赖它的0079；确认schema与最小DB权限后，由批准的初始化/恢复SOP写首条绑定并核验角色、tenant、顾问代次、责任人和审计（无脚本/权限批准即停止上线）；显式装配并验证私有附件后端、备份/恢复及留存/孤儿治理；最后才允许切换本刀代码并做受保护API验收。不得先切代码再补迁移/种子/附件。当前仅Draft，这份清单不是生产执行授权。初始化/恢复脚本仍未提供，孤儿清理策略及隔离/备份恢复验收仍待另批，禁止自动删除或磁盘回退。未来新增管理方法/路径必须同步审advisor_request门禁、main_fixture路由清单和端点矩阵；list扩展继续显式字段白名单与审计检查。

`tests/sem_phase1a_main_fixture.py`在独立进程导入实际main.app，真实JWT及生产装配、角色/账户/来源/规划表全部为临时合成数据，无require_auth/principal/服务替身、不进入lifespan、不启动调度器、不读.env/网络。仅让真实数据库factory采用适用SQLite的pool选项。`test_sem_phase1a_slice5.py`对15端点×29状态参数化435项：原26态加有效顾问、内置管理员、平台管理员的真实15维HTTP结果。顾问管理GET/两个POST固定403并验证无绑定/审计变化，顾问审批因生产资产/账户帽未核验仍为422/DUPLICATE_BLOCKED，不伪报审批成功；两类管理员仅三个管理端点200，实际撤销后重授。另有首绑/最后绑定撤销×两类管理员×三个端点12项参数回归，以及未绑定账户/即时撤销/来源更新失效/附件默认失败/真实OpenAPI清单与未列路径。独立进程在导入main前将start_scheduler设为调用即失败的spy，并断言零调用，ASGITransport不进入lifespan。保留phase0、1a、slice2/3/4及迁移完整回归。

新增原生PG用例仅接受已有SEM_ALERT_TEST_DATABASE_URL的loopback/sem_writeback_test，在随机schema实际0077→0078→0079、跨scope FK/只追加拒绝、来源并发仅一次成功、重启/hash读取、附件写失败回滚/后端缺失失败、来源新版本使规划立即失效；无URL本地skip。现有CI完整pytest收集执行，最终必须从本提交日志核对SLICE5_NATIVE_PG_EXECUTED标记；本地SQLite不算PG通过，不改.github。

挂入口后上线前仍要：另审生产0078脏绑定只读巡检/获批清理、账户复合索引扫描/锁窗口及0079新增表/索引/触发器安装窗口；按实际DB角色另审最小权限，本刀不扩sem_runtime；实现并显式装配私有附件后端（ACL/不可变写/限额/超时/回读/保留期/备份/孤儿治理），不得新增临时磁盘回退；另行批准首次账户授权初始化/恢复SOP；另审前端入口和真实顾问使用路径、预算帽/资产核验及来源格式提示。本刀无前端入口，API被授权后可通过客户端调用；OpenAPI存在新接口不代表顾问界面已上线。0078审计单列账户FK的既有残余风险继续按仅管理服务写审计SOP，不新增第二审计写入口。未来运行影子观察/上线须另批。

---

# SEM阶段1a第四刀续做（task11b）：未挂载的账户授权管理

**演练复核完成，不可执行、不可上线。** 仅task11b允许的范围A与账户授权管理。未修改`app/main.py`、共享鉴权、百度同步/OAuth或`.github`，未新增环境/配置开关。路由仅在测试显式注入的FastAPI app内挂载，未接生产入口，完整阶段1a未完成。以下第四刀说明为当前口径，后面的第三/二刀内容保留为历史。

开发时间：本轮从status11的“续做 步骤1”开始，提交、CI与封存时间见外部交接；不含人工审查、生产迁移或影子观察。

## review12三项与建议

1. `SQLAlchemyShadowStore.cleanup_previews`在cleanup单次自有连接/事务内以`FOR UPDATE SKIP LOCKED`选中到期预览再删除，与apply持锁行互斥；cleanup与apply使用不同连接/事务。apply仍按plan→preview锁定；清理跳过任何被读/apply持锁的预览，可先回收其他到期预览，后续重试再回收跳过行。SQLite两种存储使用`BEGIN IMMEDIATE`串行写，不把SQLite等同于PG行锁。新增原生PG测试让真实apply在取得preview行锁后暂停，验证清理跳过它、删除另一行，释放后apply成功；本地无已有临时PG URL时skip。
2. 仅新增`0078_sem_phase1a_grants.py`，接原唯一head0077。PG给`baidu_accounts(id,tenant_id)`加复合唯一索引（id原有主键已保证逻辑唯一）并给新绑定表加复合FK；父账户归属变动同样受限。SQLite用绑定INSERT/UPDATE与父账户id/tenant UPDATE触发器实现等价校验，不重建/删除表。迁移先拒绝已有脏绑定，不自动修复数据；新增绑定generation（旧行0）和授权审计表。旧迁移完全不动，downgrade拒绝，无GRANT/sem_runtime权限变更。唯一索引的构建开销和加锁仍需生产操作前另审，本刀仅在临时空库验证。
3. slice2 API helper强制显式传入`principal_dependency(adapter(auth_db), …)`，共用授权夹具；服务/store单元测试仍可直接principal并注明。API ScopeDenied按读取/顾问提交意图区分两条固定脱敏文案，Excel导出虽为GET仍有审计写入，按写处理。生产真实会话夹具明确断言同租户active但未绑定204账户不可见。新增业务异常断言使用`pytest.raises(ShadowError)`。

## 管理服务与路由工厂

`AccountGrantService(transaction_factory)`只接受显式注入的AsyncSession事务工厂（如`async_sessionmaker.begin`），不读URL/config、不创建engine/DDL。`create_grant_router(service)`默认直接复用现有`require_admin -> require_auth`；不定义新角色。每次服务调用在同一事务中重新锁定/核对数据库管理员用户、角色、tenant、百度账户；授予时还锁定目标用户/角色及当前有效顾问grant，校验user/tenant/代次和顾问默认tenant有效；客户只可绑定自身tenant且无advisor_grant_id。沿用生产适配器的顾问/只读客户判定。API Key匿名超管因无可归属审计user_id拒绝，真实全局内置管理员与满足现有平台管理权限的全局自定义角色可用。

| 路由（均未注册生产） | 请求与用途 |
|---|---|
| GET `/api/v1/sem/phase1a/account-grants/accounts/{account_id}?tenant_id=…` | 列出单账户绑定（含撤销状态/代次），不返回用户名/凭证 |
| POST 同路径 | `{tenant_id,user_id,advisor_grant_id?}`；授予顾问或客户 |
| POST 同路径`/revoke` | `{tenant_id,user_id}`；撤销单账户绑定 |

重复相同有效授权/重复撤销不新增审计或代次。首次授予generation=1，撤销保持代次，再授予递增；顾问tenant grant变代次时必须绑定新grant_id。绑定变更与审计（actor/user/tenant/account/advisor_grant_id/generation/action/UTC时间）同事务，审计失败全回滚；无输入理由/名称字段，不回显不可信输入或底层异常。按账户锁串行化首次授予/撤销/重授；SQLite在读取前取得写锁。撤销后下次principal解析立即失去该账户，不跨请求缓存。撤销允许目标已变角色/停用或账户已归档，避免无法收回旧绑定。

review14修复：列出、授予（含幂等请求）和撤销均在同事务读取并锁定对应`tenant_modules`的SEM记录，复用现有`module_is_available`策略：仅active/trial且未过期（含到期当天）可用；suspended/closed/过期/缺失一律403 `GRANT_MODULE_UNAVAILABLE`，两类管理员及直接服务调用一致，拒绝时绑定/代次/审计不变。账户归档仍可撤销的前提是SEM模块可用；挂起期间全部管理操作关闭，恢复后再操作。

审计运营SOP：`sem_phase1a_grant_audit`当前只有account单列FK，没有(account_id,tenant_id)复合约束，不能声称数据库会拒绝审计跨租户写入。审计只允许由`AccountGrantService`在同事务核对账户tenant后随绑定变更写入；禁止脚本/直接SQL/其他服务绕过此入口创建或改写审计。若后续需要其他写入口，须先单独审查新增迁移及复合约束，并补跨tenant拒绝测试；本轮不改0078、不执行生产SQL。

错误码：未登录401；非平台管理员403（现有require_admin）；服务复核拒绝`GRANT_ADMIN_REQUIRED`/`GRANT_IDENTITY_UNAVAILABLE`/`GRANT_ROLE_INVALID`（403）；账户/目标租户/角色/active校验422；顾问授权代次无效`GRANT_ADVISOR_GENERATION_INVALID`（409）；数据库完整性冲突`GRANT_CONFLICT`（409）；存储/解析不可用`GRANT_STORAGE_UNAVAILABLE`（503）；请求契约422/`CONTRACT_INVALID`。均为固定文案。

## 验证、挂载阻塞与下一刀

```powershell
py -3.13 -X utf8 -m pytest -q tests/test_sem_phase0.py tests/test_sem_phase1a.py tests/test_sem_phase1a_slice2.py tests/test_sem_phase1a_slice3.py tests/test_sem_phase1a_slice4.py tests/test_seo_migration_merge.py
```

真实JWT管理接口在隔离进程使用临时合成SQLite和纯内存签名/测试配置验证所有端点未登录401、顾问/客户403、管理员与平台管理员正向、幂等、即时撤销、客户只读、DB角色变化、审计失败回滚及错误脱敏。SQLite实际执行0077→0078 upgrade与跨租户INSERT/UPDATE/父归属变更拒绝；不导入迁移env、不连接生产。最终仍要求现有主CI完整`python -m pytest -q tests`全绿，并从日志核对`SLICE4_NATIVE_PG_EXECUTED: cleanup_locked_apply + composite_tenant_fk PASS`，该标记只在新增原生PG所有断言通过后输出；无URL本地skip不算PG通过。沿用仅loopback/sem_writeback_test/随机隔离schema的现有CI能力，不新建CI配置；随机schema随临时服务销毁。

**挂路由留待用户决定**：阶段0来源/附件目前只有显式本地SQLite持久化；影子服务创建和每次读取必须重新核对来源版本/hash。生产挂载需要先确定阶段0来源与附件生产存储、接入/注入、ACL/留存及隔离/配额/超时的授权范围，再审真实顾问路径门禁。本刀没有创建替代来源/绕过检查或改生产入口。真实抓取/OCR/模型外发、百度执行文件/上传/执行/启用/自动暂停、正式客户确认、情况②、前端仍不做；无生产数据/服务器/库操作。

完整交接和结果入口见[HANDOFF_INDEX.md](HANDOFF_INDEX.md)。

---

# SEM阶段1a第三刀历史：账户隔离与未挂载的生产适配代码

**演练复核完成，不可执行、不可上线。** 仅task10第三刀，完整1a未完成。真实页面/OCR/模型/百度执行、正式客户确认、情况②均关闭。未挂app.main、未改生产入口/CI/共享鉴权、未扩sem_runtime权限、未连接生产库。下方第二刀文档保留为历史口径，以本节为准。

## 账户与角色

本地合成`LocalGrantPrincipalAdapter`每请求以只读连接核对`users.role`与`SessionIdentity.role`，不一致拒绝。该快照role字段为测试简化字段，生产真实角色使用`users.role_id -> roles`，两者不混用。clock必须返回带时区datetime；数据库历史naive锁定时间按UTC解释。

第三刀新增`sem_phase1a_account_grants(user_id, tenant_id, account_id, advisor_grant_id, revoked_at)`；第四刀0078追加`generation`与`sem_phase1a_grant_audit`审计表，并提供未挂载的管理API，当前schema及管理契约以上方第四刀章节为准。不是tenant通配授权。顾问必须同时有当前未撤销tenant grant及精确账户绑定，绑定的advisor_grant_id须匹配会话代次；客户仅自身tenant和advisor_grant_id为空的账户绑定可读，writable永为空。账户还必须active且归属一致。缺表/缺绑定/撤销/旧代次/角色错配均关闭；同tenant其余active账户不自动获得权限。第三刀当时无授权写入API；两刀均无回填或生产授权修复。

`ProductionPrincipalAdapter`接收现有真实`AuthContext`及显式注入的AsyncSession，重读DB用户/角色，复用`is_advisor`、`read_grants`/`active_grants`、`ensure_module_access`和`ensure_sem_identity_access`；拒绝API Key超管、过期/停用/锁定/角色错配/缺选客户/旧grant/跨tenant/无账户绑定。内置品牌方客户资产菜单的既有edit权限不转为规划写权限。

`production_principal_dependency()`工厂直接依赖现有`require_auth`（JWT签名/期限/角色/会话/撤销检查），不解析裸Header身份、不新增JWT机制或环境开关、不注册路由。**现有advisor_request仍拒绝未开放的新路径和顾问写请求**，本刀未修改、绕过或放宽该门禁。隔离测试在现有允许的`/auth/me`会话路径验证真实JWT→AuthContext→principal；第三刀API全正向用同一LocalGrantPrincipalAdapter合成授权库。真实顾问访问第三刀路由仍被现有门禁拒绝，正式接入需下一刀单独审查，不以本刀适配代码声称已开放。

review11修复：本地和生产适配器在resolve阶段即拒绝空有效账户集合；生产依赖保留既有鉴权/模块/归属检查的HTTPException状态码、detail及headers，仅对ScopeDenied和存储/解析异常返回固定脱敏403。第一刀API回归也复用`tests/sem_phase1a_auth_fixture.py`中的授权库与LocalGrant适配器；直接构造principal仅用于服务/check_scope单元测试。

### 账户绑定运营SOP（本刀无写入口）

0077的独立外键不能保证绑定tenant与账户tenant相等；第三刀当时禁止修改已存在迁移、回填授权或连接生产，故保留此数据库约束缺口。此历史缺口已由第四刀新增0078数据库约束闭合，以上方第四刀迁移章节为准。读取JOIN仍要求`g.tenant_id=a.tenant_id`，跨租户脏绑定不会授予权限，无剩余有效绑定时resolve直接拒绝；两种适配器均有回归。

后续获单独授权的provisioning流程必须在同一事务中先锁定并核对用户、账户、tenant与当前未撤销advisor grant，要求账户tenant=绑定tenant、账户active，顾问grant的user/tenant/代次一致，客户tenant一致且advisor_grant_id为空；任何不符拒绝写入并留审计。上线前只读巡检绑定与账户tenant不相等、grant归属不符的记录，发现即停止该批开通，由另获授权的流程处理，不自动修复。本刀未提供或执行此巡检/写入工具；下一刀需设计复合FK或管理端事务校验，再审查接线。

## PostgreSQL存储与新增迁移

`SQLAlchemyShadowStore(connection_factory)`实现同一ShadowStore协议，典型参数是调用方显式提供的`Engine.begin`。不创建engine、不读取URL/config/.env、不执行DDL，不默认使用app.database全局engine。每请求独立事务；PostgreSQL按plan→preview行锁，内部revision CAS覆盖审计写入，预览消费和规划/审批/审计同事务，任一flush失败全回滚。第三刀cleanup策略已被第四刀取代：PostgreSQL在同一事务内先以`FOR UPDATE SKIP LOCKED`选到期且未持锁的预览再DELETE，跳过正在读/apply的行；SQLite使用BEGIN IMMEDIATE，测试验证清理等待写锁。两种数据库的等待/跳过行为不同，详见上方第四刀章节。

仅新增`migrations/versions/0077_sem_phase1a_shadow.py`，down_revision为原唯一head `0076_oauth_rebind_intent`。增加上述账户绑定表及`sem_phase1a_shadow_plans`/`sem_phase1a_shadow_previews`（id/revision/payload/expires_at、预览到期索引）。旧迁移不动，只加不删，downgrade明确拒绝，不含权限GRANT或角色修改。迁移未在任何生产库执行。现有phase0来源/截图存储接口仍单独注入；本刀服务仍限定合成fixture账户，不是生产可用入口。

本地用临时SQLite实际执行新增upgrade（不导入migrations/env.py）及可替换存储重启/一次应用/CAS/第二次flush失败全回滚。原生PostgreSQL测试只接受现有CI的SEM_ALERT_TEST_DATABASE_URL、loopback和sem_writeback_test库，创建随机隔离schema，不读取应用DATABASE_URL、不删除已有表、不新增CI服务/配置；CI临时服务随任务销毁。无该本地测试服务时明确skip，不伪报原生验证。旧迁移hash检查以Git LF换行校验，兼容Windows CRLF checkout；未改变旧迁移。

## 演练状态、错误与审计

所有规划响应强制`executable=false`、`go_live_allowed=false`、正式确认pending、执行导出/启用false。`review_status_label`明确“演练复核完成，不可执行、不可上线”；`rehearsal_only_blockers`保留P6未知项和正式确认/执行/上线硬门禁。预览同样不可执行；Excel逐行复核文案及只读绑定页写入这些限制，不把advisor_review_complete当作P6/上线放行。无前端UI被挂载。

业务条件使用专用ShadowError：PREVIEW_AUDIENCE_ADVISOR_ONLY、RULING_SOURCE_INVALID、RULING_REQUIRED、APPROVAL_ROWS_INVALID、ADVISOR_REVIEW_REQUIRED。PermissionError固定403/OPERATION_FORBIDDEN，契约ValueError仍422/CONTRACT_INVALID；均不回显输入。结构逐操作审计新增step_index，单请求同版本仍可定位步骤。phase0 ScopeDenied区分读取和顾问提交。

## 复现与交接索引

```powershell
py -3.13 -X utf8 -m pytest -q tests/test_sem_phase0.py tests/test_sem_phase1a.py tests/test_sem_phase1a_slice2.py tests/test_sem_phase1a_slice3.py tests/test_seo_migration_merge.py
py -3.13 -X utf8 -m app.sem_phase1a.demo_slice3 --output docs/sem-phase1a/samples
```

**review11后的完整验收要求**：以上本地切片命令须全部运行，不能以单个文件/筛选子集替代；最终CI还必须运行现有主job的完整`python -m pytest -q tests`，并核对日志中`test_postgres_existing_ci_service_once_concurrency_and_rollback`实际通过而非skip。CI沿用现有显式`SEM_ALERT_TEST_DATABASE_URL`，不修改.github配置。本机无该临时服务时原生PG用例会skip，SQLite结果不代表已验证FOR UPDATE与PG双连接并发。原生PG仅在CI验证；随机schema只允许留在可销毁的`sem_writeback_test`库，随服务销毁，不删应用表。

样例`slice3-auth.internal.json`（部分账户授权/DB角色拒绝）、`slice3-review.internal.json`及`slice3-review.internal.xlsx`（全行演练复核后仍不可执行）、`slice3-persistence.internal.json`（重启与重放拒绝），均为TEMP合成库实际运行结果，无真实凭证。Excel只更新语义与绑定字段，未声称新增原生Excel视觉验收。交接入口见[HANDOFF_INDEX.md](HANDOFF_INDEX.md)。

---

以下为第二刀历史说明（其“未新增迁移/未实现真实适配”等描述仅适用于第二刀）。

# SEM阶段1a第二刀：持久化合成影子规划

**内部规划/演练，不可上传百度。** 只覆盖①新开户、③新品/活动；基线第一刀11a49247（Draft #819，依赖#818）。本刀开发时间估算12～20h，完整1a仍估算85～135h；估算不代表实际耗时。代码不注册app.main，不扩sem_runtime，不新增生产迁移，不连接生产库。真实HTTP/OCR/模型、情况②、正式客户确认和P9以后执行继续关闭。

## 持久化与并发

`ShadowStore`/`Transaction`/`Records`是可替换接口，当前实现`SQLiteShadowStore(Path(...))`只接受显式本地路径。`ShadowService(submission_store, shadow_store)`推荐显式注入；省略第二参数时，在显式phase0数据库同目录创建独立的`<stem>.shadow.sqlite3`，不读取配置或环境变量。必须使用专用合成目录或TEMP；没有应用全局存储或生产迁移。

规划、来源、裁定、审批、历史、审计和预览均写入独立SQLite；服务没有跨请求规划/预览缓存。每次操作`BEGIN IMMEDIATE`，按需加载记录，提交时以内部storage revision做CAS更新；它覆盖审计/审批等不改变内容版本的写入。内容修改另检查客户端`expected_version`并递增规划版本。多连接/多进程同预览竞争只有一次成功；预览消费标记、规划版本/行、清空旧审批及审计在同一事务提交，任意提交错误全部回滚。SQLite是本机演练持久化，不宣称分布式或生产高可用。

预览默认TTL=3600秒，可通过构造参数注入测试时钟/TTL，返回`expires_at`（UTC Unix秒）。应用时检查过期；`cleanup_previews()`删除到期预览，创建规划或预览时也执行清理。删除不影响规划中的审计。没有后台任务或生产调度器。此段为第二刀历史说明；PG的`FOR UPDATE SKIP LOCKED`与SQLite写锁以文首第四刀第1条为准。

每次读取规划，检查所有引用页的阶段0版本、hash及新版本；任一页有新版本即409，必须重建。phase0读取时也重验LandingSubmission、SHA-256、tenant/account/page与revision绑定；存储脏数据拒绝。返回值均为独立快照。

## 只读权限适配

`PrincipalAdapter.resolve(SessionIdentity)`是接口；`principal_dependency(adapter, resolve_identity)`生成未挂载的FastAPI依赖。`resolve_identity`必须由可信会话层提供，负责真实认证和既有顾问角色判定；不接受客户端JSON、裸Header或查询参数冒充身份。此刀只实现`LocalGrantPrincipalAdapter`，通过SQLite `mode=ro`及`query_only`读取**本地合成授权快照**，没有真实会话/生产库连接。

字段语义对照现有`security/advisor_scope.py`、`module_scope.py`及models：users停用/锁定、用户限定tenant、当前会话tenant/grant_id、advisor_tenant_grants当前未撤销代次、tenant实体存在、baidu_accounts归属及active状态；SEM仅active/trial且未过期可读写，suspended/closed/缺失一律拒绝。每次依赖解析重新查询，无授权缓存；缺表/非法数据fail closed，不降级到全租户权限。

顾问可写当前授权账户；客户只读自身tenant的规划JSON和到期建议，没有写账户集合。客户不能创建、裁定、编辑、预览上传、应用、审批或触发带审计写入的Excel导出。底层可信Principal注入接口继续供合成测试使用，调用方不得跨请求缓存授权结果。真实认证、角色映射及生产适配仍需后续另批，不把合成快照当生产身份。

## 多产品线、多页与结构编辑

`POST /api/v1/sem/phase1a/shadow/plans/batch`接受`tenant_id`、`account_id`、`pages:[{page_id,submission_revision,fixture_id}]`。1～20个不重复页面，全部属于同账户，各页仍有阶段0明确声明；预算币种/周期必须相同。一个项目→每产品线一个方案→每落地页一个单元；初始单元预算取对应页声明，方案求和、项目再求和，不自动编造额度。账户帽及总声明预算继续P6硬检查；页面预算边界文本/引用不能被Excel覆盖。来源ID和字段按页隔离，冲突默认值显式按HTML→假OCR→submission优先级排序，输入列表顺序不影响结果。

`POST /plans/{plan_id}/structure`接受`expected_version`、`reason`、`operations`（1～100项）：

| action | 参数/行为 |
|---|---|
| add_campaign | parent_id=项目，text、budget_cents；可选source_refs，默认继承父行来源；返回服务端新行ID |
| add_unit | parent_id=方案，text、budget_cents；来源规则同上 |
| update | row_id=方案/单元，可改text或budget_cents；不能改身份/父级/来源 |
| delete | row_id=方案/单元，级联删除其后代；项目不能删除 |
| move_keyword | row_id=关键词，parent_id=目标单元；保留原来源，标待核实 |

同请求原子提交、一次内容版本递增，全部旧审批失效；失败连同先前操作全部回滚。每项操作记录操作者、时间、理由、操作参数、受影响行的前后值及当时P5/P6报告。允许保存预算待平衡或方案暂无单元的阻断草稿，方便逐步结构编辑；这类草稿不能通过顾问演练复核。可同请求批量平衡已有行预算。新增方案后取得服务端ID，再新增其单元。总行数≤1000；Excel仍仅修改既有行内容/预算，不承担结构增删。

P5在本批跨单元及合成既有资产中按NFKC/空白/大小写归一查同类精确重复。P6检查结构/预算树、账户帽、总声明、来源、字数、否词和裁定；每个冲突字段必须在最近裁定中具备与当前selected一致的source_id、原文hash、顾问、理由和时间。顾问提交裁定时把默认选择也逐字段记入decisions。演练逐项审批不修改来源核实状态，不解除未知平台规则/线上事实/推断待核实阻断；客户确认始终pending。

否词按词/短语边界匹配：NFKC/casefold后，连续汉字段为一个词，空白/标点/汉字与拉丁数字切换构成边界；短语要求连续完整词序列。例如`free`不命中`carefree`，`费`不命中`费用咨询`，`免费`不命中未分词的`免费试用`；`免费 维修`命中`免费，维修`。不调用分词/OCR/外部服务，未分词复合语义不作完整语言理解保证。否词只作用于其父方案/单元的后代，移动关键词立即重查作用域。无截止显示「无截止」，原始来源JSON仍保留真实null。

## 错误、安全与关闭的出口

API错误固定为`detail:{code,message}`，不回显不可信输入或原始异常。主要code：CONTRACT_INVALID、EXCEL_INVALID_OR_TAMPERED、BUDGET_INVALID、DUPLICATE_BLOCKED、VERSION_CONFLICT、SCOPE_DENIED、PREVIEW_EXPIRED/PREVIEW_NOT_FOUND、STRUCTURE_INVALID、CONFLICT_UNRESOLVED、NEGATIVE_OVERLAP、TEXT_LIMIT、SOURCE_INVALID。请求体/路径/查询校验错误也统一脱敏。

截图按魔数/解码确定格式，白名单PNG/JPEG/WebP；MIME或扩展名不匹配只返回静态warnings，不拒收合法图片。仍限单图10MiB、合计30MiB、10张、20M像素、单边10000、单帧；重新编码PNG删除元数据，不识别/OCR，不访问图内URL。

内部XLSX绑定规划ID/版本/hash/来源hash/用途；禁止改身份、来源、核实/审批，禁止公式/宏/外部引用/ZIP超限。沿用第一刀内部格式，未新增百度文件或UI。旧的excel/{advisor|customer}、previews/{audience}、apply-preview、approvals等接口保持演练语义。无execute/enable/baidu-export/customer-confirm路由，export_execution和enable_plan无条件拒绝；审批也不能打开执行。

## 复现与样例

```powershell
python -m pytest -q tests/test_sem_phase0.py tests/test_sem_phase1a.py tests/test_sem_phase1a_slice2.py
python -m app.sem_phase1a.demo_slice2 --output docs/sem-phase1a/samples
```

新fixture：`fixtures/slice2-pages.internal.json`，全合成example.invalid地址。四份新JSON：`slice2-multi-plan.internal.json`、`slice2-structure.internal.json`、`slice2-persistence.internal.json`、`slice2-auth.internal.json`，分别展示两产品线三页、结构审计/复检、重启与一次应用/重放拒绝、顾问/客户及暂停拒绝。所有数据库在TEMP创建并销毁；样例包含随机演练ID和时间，不是客户凭证。第一刀已有XLSX及JSON保留为历史样例，本刀未改其版式，不声称新增原生Excel验收。

合成测试覆盖多进程/多连接、存储CAS、提交故障回滚、预览TTL、重启、权限撤销/暂停/跨tenant、客户只读、批量来源/预算、结构操作与原子性、逐字段P6裁定、中文否词、截图及结构化错误。CI配置未改；已有CI自动收集新增测试。

## 下一刀入口

本刀完成后即停。附件ACL/留存、解码隔离与配额/超时、真实会话/数据库适配、真实HTTP/OCR供应商及模型、正式客户确认/凭证、情况②和百度正式模板/执行均未做，需另定范围。仅本地合成测试与持久化，不替代PLAN的影子天数/账户/独立样本门槛；保持Draft，不合并、不部署。

# SEM阶段1a第三刀：账户隔离与未挂载的生产适配代码

**演练复核完成，不可执行、不可上线。** 仅task10第三刀，完整1a未完成。真实页面/OCR/模型/百度执行、正式客户确认、情况②均关闭。未挂app.main、未改生产入口/CI/共享鉴权、未扩sem_runtime权限、未连接生产库。下方第二刀文档保留为历史口径，以本节为准。

## 账户与角色

本地合成`LocalGrantPrincipalAdapter`每请求以只读连接核对`users.role`与`SessionIdentity.role`，不一致拒绝。该快照role字段为测试简化字段，生产真实角色使用`users.role_id -> roles`，两者不混用。clock必须返回带时区datetime；数据库历史naive锁定时间按UTC解释。

新增`sem_phase1a_account_grants(user_id, tenant_id, account_id, advisor_grant_id, revoked_at)`，不是tenant通配授权。顾问必须同时有当前未撤销tenant grant及精确账户绑定，绑定的advisor_grant_id须匹配会话代次；客户仅自身tenant和advisor_grant_id为空的账户绑定可读，writable永为空。账户还必须active且归属一致。缺表/缺绑定/撤销/旧代次/角色错配均关闭；同tenant其余active账户不自动获得权限。无新增授权写入API、无回填或生产授权修复。

`ProductionPrincipalAdapter`接收现有真实`AuthContext`及显式注入的AsyncSession，重读DB用户/角色，复用`is_advisor`、`read_grants`/`active_grants`、`ensure_module_access`和`ensure_sem_identity_access`；拒绝API Key超管、过期/停用/锁定/角色错配/缺选客户/旧grant/跨tenant/无账户绑定。内置品牌方客户资产菜单的既有edit权限不转为规划写权限。

`production_principal_dependency()`工厂直接依赖现有`require_auth`（JWT签名/期限/角色/会话/撤销检查），不解析裸Header身份、不新增JWT机制或环境开关、不注册路由。**现有advisor_request仍拒绝未开放的新路径和顾问写请求**，本刀未修改、绕过或放宽该门禁。隔离测试在现有允许的`/auth/me`会话路径验证真实JWT→AuthContext→principal；第三刀API全正向用同一LocalGrantPrincipalAdapter合成授权库。真实顾问访问第三刀路由仍被现有门禁拒绝，正式接入需下一刀单独审查，不以本刀适配代码声称已开放。

## PostgreSQL存储与新增迁移

`SQLAlchemyShadowStore(connection_factory)`实现同一ShadowStore协议，典型参数是调用方显式提供的`Engine.begin`。不创建engine、不读取URL/config/.env、不执行DDL，不默认使用app.database全局engine。每请求独立事务；PostgreSQL按plan→preview行锁，内部revision CAS覆盖审计写入，预览消费和规划/审批/审计同事务，任一flush失败全回滚。cleanup的DELETE使用相同行锁，SQLite原实现同样使用BEGIN IMMEDIATE；测试验证清理等待持锁事务。

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

样例`slice3-auth.internal.json`（部分账户授权/DB角色拒绝）、`slice3-review.internal.json`及`slice3-review.internal.xlsx`（全行演练复核后仍不可执行）、`slice3-persistence.internal.json`（重启与重放拒绝），均为TEMP合成库实际运行结果，无真实凭证。Excel只更新语义与绑定字段，未声称新增原生Excel视觉验收。交接入口见[HANDOFF_INDEX.md](HANDOFF_INDEX.md)。

---

以下为第二刀历史说明（其“未新增迁移/未实现真实适配”等描述仅适用于第二刀）。

# SEM阶段1a第二刀：持久化合成影子规划

**内部规划/演练，不可上传百度。** 只覆盖①新开户、③新品/活动；基线第一刀11a49247（Draft #819，依赖#818）。本刀开发时间估算12～20h，完整1a仍估算85～135h；估算不代表实际耗时。代码不注册app.main，不扩sem_runtime，不新增生产迁移，不连接生产库。真实HTTP/OCR/模型、情况②、正式客户确认和P9以后执行继续关闭。

## 持久化与并发

`ShadowStore`/`Transaction`/`Records`是可替换接口，当前实现`SQLiteShadowStore(Path(...))`只接受显式本地路径。`ShadowService(submission_store, shadow_store)`推荐显式注入；省略第二参数时，在显式phase0数据库同目录创建独立的`<stem>.shadow.sqlite3`，不读取配置或环境变量。必须使用专用合成目录或TEMP；没有应用全局存储或生产迁移。

规划、来源、裁定、审批、历史、审计和预览均写入独立SQLite；服务没有跨请求规划/预览缓存。每次操作`BEGIN IMMEDIATE`，按需加载记录，提交时以内部storage revision做CAS更新；它覆盖审计/审批等不改变内容版本的写入。内容修改另检查客户端`expected_version`并递增规划版本。多连接/多进程同预览竞争只有一次成功；预览消费标记、规划版本/行、清空旧审批及审计在同一事务提交，任意提交错误全部回滚。SQLite是本机演练持久化，不宣称分布式或生产高可用。

预览默认TTL=3600秒，可通过构造参数注入测试时钟/TTL，返回`expires_at`（UTC Unix秒）。应用时检查过期；`cleanup_previews()`删除到期预览，创建规划或预览时也执行清理。删除不影响规划中的审计。没有后台任务或生产调度器。

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

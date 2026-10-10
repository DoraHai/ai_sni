# 调用管理结构与集成上线审核包

日期：2026-10-11。PR #649 待审；本包未授权生产 DDL、合并、部署或开关变更。
脚本原文为审核权威：[schema](../scripts/api_controls_schema.sql)、[permissions](../scripts/api_controls_permissions.sql)。本次没有改 SQL。

## 已核对的生产事实

通过 systemd MainPID 对应进程的环境在服务器内部创建连接，使用只读事务访问 catalog；
不打印 DSN、凭据、加密主密钥或配置值，不查询模型，不写业务数据。

| 实际单元 | 运行 | 计量实际值 | 管理实际值 | 新并发/未知费用准入代码 |
| --- | --- | --- | --- | --- |
| sem-backend.service | active | true | 未设置，实际 false | 尚未发布 |
| seo-service.service | active | true | 未设置，实际 false | 尚未发布 |
| geo-service.service | active | true | 未设置，实际 false | 尚未发布 |

三个连接的数据库名、服务器地址与端口在内部比对一致；运行角色均为脚本目标 sem_runtime。
三进程加密主密钥内部比对一致，仅报告布尔结果。
public.api_usage_events 存在，reserved_amount 不存在；四张管理表都不存在，属于完整未安装，未发现这五个对象的部分安装。
现有 ledger 的有效运行权限是 SELECT/INSERT/UPDATE，DELETE=false；角色 superuser/createdb/createrole/public CREATE 均 false。
三份已发布 api_controls.py 的 SHA256 相同：c5ae342abd875fadabbe968db70288276214d64468af627556c49999e14cbc3a。
虽然都有 LOCK_ID=714102026，均无本轮新准入分支；锁常量相同不能证明调用链、结构和开关已就绪。
以上是此次核验快照，执行前须重查，不能用本报告替代部署后证据。

SEM 阿里云余额 AK 两字段不存在；DeepSeek key 存在；Kimi key 仅 GEO 存在，尚未接通工作台管理凭据。
余额查询是否可用与调用计量、预算保护是独立验收项；配置模型 key 不能证明账务查询权限。

## schema.sql 的完整变更

BEGIN → lock_timeout=3s、statement_timeout=15s → ALTER/CREATE → COMMIT，PostgreSQL 原子事务。
所有名称未限定 schema，执行者必须先核对 current_schema/search_path 是目标 public；隔离测试只用自己的随机 schema。
依赖既有 api_usage_events；没有创建费用台账、角色、数据库或业务表，没有 Alembic stamp、预算初值或历史费用追补。

| 对象 | 列、类型、默认及约束 |
| --- | --- |
| api_usage_events 新列 | reserved_amount numeric(24,12)，可 NULL，CHECK >=0；NULL 表示无可信预留，绝不默认零 |
| api_control_settings | key varchar(260) PK；kind varchar(16) NOT NULL，CHECK budget/provider/rate/connection；value jsonb NOT NULL，CHECK object；revision integer NOT NULL CHECK >0；updated_by bigint NOT NULL；updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP |
| api_control_bindings | id varchar(64)、module varchar(12)、label varchar(100)、host varchar(200) 均 NOT NULL；model varchar(200) 可 NULL；configured/can_rotate boolean NOT NULL；metadata jsonb NOT NULL DEFAULT '{}' CHECK object；seen_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP；PK(module,label)，id 非唯一键 |
| api_control_credentials | id varchar(64) PK；ciphertext text 可 NULL（恢复原配置）；revision integer NOT NULL CHECK >0；updated_by bigint NOT NULL；updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP |
| api_control_audit | id uuid PK；actor_id bigint、resource varchar(260)、action varchar(32)、request_hash varchar(64) 均 NOT NULL；before_value jsonb 可 NULL；after_value jsonb NOT NULL；created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP |
| 索引 | api_control_audit_created_idx：api_control_audit(created_at DESC) |

没有序列、IDENTITY、自增、外键、触发器、RLS 或预算种子；身份引用依靠已有鉴权和应用校验，DDL 本身不验证用户/客户存在。
max_concurrent 是原 budget JSON 可选字段，provider:<host> 是原 budget key 范围，无新增 DDL。
credentials 只存密文；运行角色仍可读密文，必须保留主密钥保护与既有超管鉴权。

## permissions.sql 的完整权限

脚本由既有对象所有者执行，BEGIN、同样 3s/15s 超时、COMMIT。运行角色没有安装能力。

| 对象 | 对 PUBLIC、sem_runtime 先做 | 随后授予 sem_runtime |
| --- | --- | --- |
| settings、bindings、credentials | REVOKE ALL | SELECT、INSERT、UPDATE |
| audit | REVOKE ALL | SELECT、INSERT |

不授予 DELETE、TRUNCATE、REFERENCES、TRIGGER、审计 UPDATE、schema CREATE 或角色管理。
无序列所以无需序列授权；不修改现有 ledger 权限，另见原 api_metering_permissions.sql。
其他角色与继承权限没有被此脚本自动撤销，所有者/超级用户也仍有管理能力；安装后必须以真实运行角色核查有效权限。
三个服务当前都使用 sem_runtime；若以后独立角色，不得假设这个脚本已为其授权，需要单独审核。

## 执行顺序、重复与部分安装

1. 人工核对目标库/schema、五对象实际 catalog、当前有效权限、三服务版本/开关，记录已有对象所有者、ACL、索引和约束。备份结构/ACL；核对并发 DDL 锁窗口。
2. 仅在 ledger 已存在、reserved_amount 与四表全部未安装时，由对象所有者执行完整 schema.sql。使用客户端遇错即停，核对 COMMIT 成功及全部类型、约束、PK、索引；不能删原 ledger。
3. 在新表全部正确时执行 permissions.sql，核查运行角色实际有效权限。schema 和权限是两次独立事务，权限失败不会撤销已提交结构；保持管理关闭。
4. 脚本没有 IF NOT EXISTS。结构完全安装后不得重复 schema.sql；重复会在重复列/表处失败并回滚该次事务，不会把它当成功。
5. 正常单次 PostgreSQL DDL 事务失败应整体回滚。若发现部分安装，先记录差异与原因，不盲重跑、不跳过错误、不 DROP/CASCADE；由人工准备逐对象修复脚本另审。准入 helper 检查四表和预留列，缺任一项就拒绝。
6. helper 只做必要对象存在检查，不能替代安装审核中的全部列/类型/约束/权限核对。拥有相同表名但错误结构也不可上线；查询/写入异常会拒绝调用。
7. 权限脚本在结构正确且角色/所有者正确时可重新执行 revoke/grant 来恢复目标权限；必须核查继承权限，不能以脚本返回零证明审计不可 UPDATE。

不以 ledger 已在生产为管理 DDL 已获准。人工审批是 AGENTS.md 的迁移要求，本轮没有执行任何迁移。

## SEM 调用链审查与必要修复

| 调用链 | 准入入口与客户/用户依据 |
| --- | --- |
| 助手、拓词、画像、报告、开户草案等 HTTP 模型调用 | chat_json/chat_messages → metered_request；SEM middleware 固定 module='sem'；已有 AuthContext 绑定用户，ensure_tenant 校验后绑定客户 |
| 每日建议 AI、异常扫描 | 原来经过 metered_request 但后台客户未绑定；run_suggestions_for_tenant/run_rules_for_tenant 增加 business_scope('sem','tenant')，使用服务端已加载 Tenant.id，结束恢复上下文；无用户任务保持 user_id=NULL |
| 洞察、调价复核后台 | 已有 business_scope('sem','tenant') → 同一模型客户端；本轮保留 |
| 百度资产/报表/余额等 | BaiduAPIClient.call → metered_request；修复3条独立报表构造和看板构造传入已加载账户的 tenant_id/account_id；其余 _account_client 已传入 |
| 百度资金写回 | 保留原 dry-run/白名单/资金审批/行锁；准入不是资金审批，本轮不改资金机制或开关 |

模型与百度推广传输的所有已审 SEM 业务入口均走 metered_request。免费官方账务查询、OAuth 刷新、公开网页抓取不作为模型收费尝试。
SEM 历史 main 还挂有 SEO router，SEO 的 Chinaz/DataForSEO 等独立路径由模块负责审查，不能用本表宣称所有 SEO/GEO 网络客户端已经覆盖。
独立探针脚本不在本轮运行范围；手工运行的脚本若未注册可信 module，只能保持未归属，不能伪造客户。
SERVICE_MODULE 来自服务端 startup register_runtime 的固定常量；middleware/business_scope/background_scope 也只能由可信应用代码设置。
请求 body/header 中 module/tenant/user 不决定计量归属；后台持久化任务须由模块校验恢复 tenant/actor/source/version 后设置作用域。
SEM main 已在 scheduler 前 register_runtime('sem')；SEO/GEO 独立分支须各自验证 register_runtime('seo'/'geo') 和 HTTP middleware，不能照搬此 SEM 分支里的旧 main。

## 可复现的隔离联合验收

入口：tests/test_platform_call_guards.py、tests/test_platform_call_integration.py，复用 native() fixture。
显式 PLATFORM_CONSOLE_TEST_DATABASE_URL 必须指向 127.0.0.1/localhost 且数据库名含 test，否则拒绝。
fixture 创建随机 call_guards_<UUID> schema，执行实际 metering/control DDL，只建假的 tenants/users，退出清理自己的 schema；绝不使用生产 DSN。
原测试两个池；新增联合入口再开第三个独立 SQLAlchemy engine/pool，同库同 schema。
三个服务的客户端都使用 MockTransport，没有模型费用、百度请求、真实密钥或业务回写。

本机复验命令（只针对已有的自有隔离库，需先按测试配置放好假的 Settings 字段）：

```powershell
$env:DATABASE_URL='postgresql+asyncpg://balance_test@127.0.0.1:55439/platform_balance_test'
$env:PLATFORM_CONSOLE_TEST_DATABASE_URL=$env:DATABASE_URL
$env:BAIDU_APP_ID='test'; $env:BAIDU_SECRET_KEY='test'
$env:BAIDU_DEFAULT_USERNAME='test'; $env:BAIDU_DEFAULT_UCID='1'
$env:BAIDU_SELF_ACCESS_TOKEN='test'; $env:BAIDU_SELF_TOKEN_EXPIRES_AT='2030-01-01T00:00:00Z'
$env:CRYPTO_MASTER_KEY_B64='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='
$env:ADMIN_API_KEY='fixture-admin'; $env:DASHSCOPE_API_KEY='fixture'
$env:API_CONTROLS_ENABLED='false'
& 'C:/Users/Administrator/AppData/Local/Temp/onsite-tests-20261010/Scripts/python.exe' -m pytest tests/test_platform_call_guards.py tests/test_platform_call_integration.py -q
```

验证范围：四预算目标三池共享原子准入、可信进程 module 回退、伪造 header/body 不改归属、后台两引擎 actor 保留/客户绑定/上下文恢复、三百度报表零限额拒绝。
共享 guards 另覆盖 unknown 无金额策略继续占用/跨月、明确 HTTP 失败释放、金额 unknown 独立拒绝、逐表/列半安装零发送、计量关闭兼容和权限矩阵。
真实 PostgreSQL INSERT/UPDATE 故障触发器仅建在随机 schema：初始失败 provider_attempted=false，供应商后终态提交失败=true，requested 占用不释放。
三池测试模拟三个服务，非实际三个 systemd 进程；SEO/GEO 自己的独立启动/任务恢复/状态分类测试仍是上线前提，不能用此 fixture 代替。

本轮实际验证：14 个相关测试文件合计 156 passed，0 skipped（共享 guards 37、联合/SEM 入口 11 均包含在总数内），
覆盖计量/管理/余额/监控/超管/报表/账户同步/调度与建议回归；仅有既有依赖与 utcnow 弃用提示。
没有生产供应商调用或生产 SQL 变更。工作台 #650 保持原提交，UI 集成测试由总控在 #646 验收。

## 分步上线前提与验收

1. 总控按独立发布单元审核 #649、#648、#647。共享基础 3347b111 后依序取入 f49cd5af、6fc9b74a、eed858cf；SEM 客户归属补丁不整包取入 SEO/GEO。
2. 各模块回归通过，任务将 ControlDenied 和未发送 MeteringUnavailable 分类 failed，将 attempted=true 分类 unknown，禁止自动重试。核对模型/路由/用户审批保持原契约。
3. 人工审核并安排前述结构与权限执行；本轮未执行。全服务管理保持关闭，先在各独立单元发布同协议版本；监控可在原 ledger 上工作。
4. 每服务核对源码提交、固定服务 module、共享数据库/schema、LOCK_ID=714102026、运行角色有效权限与计量开关；旧 worker/旧进程全部退出后才可能启用跨服务策略。
5. 存在旧进程、管理关闭、错误 schema、运行版本未验证任一情形，不得在页面或验收声称已保护。SEM flag 不证明 SEO/GEO flag。
6. 人工核对历史 requested/unknown/未核清费用，以及现用精确模型价格。当前 deepseek-chat、DashScope -0731 缺可信新价格，金额策略可能正确拒绝；不能猜价、改模型、增加探针或释放旧占用来通过验收。
7. 负责人审核策略和启用窗口，三服务管理与计量开关一致就绪后配置显式额度。先用隔离测试证明上限与 0 暂停；生产不发额外付费验证。unknown 可能持续阻断，需要独立账务核实机制，当前没有结算按钮。
8. 工作台统一使用 #646 中整合的 #650；#650 冻结，不独立覆盖新 UI。上线后只读核对 schema/版本/开关/登记/监控与既有健康接口；任务与供应商成功分别验收。

## 回退与证据保留

DDL 事务未提交失败：由 PostgreSQL 回滚该次事务，核查实际对象，不另做 DROP。
结构成功、权限失败：保留增量结构，管理关闭，修复/复验权限后再决定启用。
应用回退：各模块沿既有发布流程回到已验证提交，保留所有 ledger、reserved_amount、管理表和审计；不得删占用或把 NULL 变零。
启用后回退旧准入代码或关闭管理都会改变后续保护，必须由负责人审核并协调三服务，不能把单服务回退后仍展示为受保护。
原 ACL 回退仅在有执行前记录时由所有者按独立审核方案恢复；不随意恢复 PUBLIC 权限。
人工核实结算仍是后续必要工作，需要供应商终态/账单证据、精确 event ID、同锁事务、幂等审计及迟到响应协议；此包不提供生产结算 SQL、强制释放或自动重试。

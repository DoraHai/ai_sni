# 未知调用核实与跨服务健康协议审核包

这是 #649 候选实现；未合并、未发布、未执行生产 SQL，未开启管理或核实开关。
生产百炼账务只读凭据已单独配置且查询成功；该配置不代表本包上线。

## 证据、关联与操作范围

超管先向供应商核对精确调用的请求记录、账单或客服结论，再提交人工声明。
本接口不联网获取证据，不判断证据文件真实性；reference/sha256/summary 是证据索引，
不是系统独立核实了供应商账单。供应商“暂未找到记录”不能证明调用已结束或免费。
无证据不能释放 requested/unknown；没有强制释放、删除或自动重试功能，不触发百度资金操作。

- GET `/api/v1/admin/console/usage/{event_id}/review` 返回 schema=1、state=available/schema_pending、row。
- POST `/api/v1/admin/console/usage/review` 返回 schema=1、state=available、replayed、row。
- snapshot.usage_reviews 返回 schema=1、state=schema_pending/ready/enabled、capabilities。
  仅 enabled 且 capability usage_review_v1 才允许前端提供核实表单。
- 两条接口均要求现有命名全局超管边界；业务租户与运维 API key 均不成为核实身份。
  成功与核实错误响应 private/no-store/Vary: Authorization；请求流最多16KiB，事务最长8秒。
- row 固定字段：id,state,endpoint,provider_request_id,started_at,estimated_amount,currency,
  review_version,verified_amount,verified_currency,reviewed_at,reviewed_provider_request_id,can_review。
  reviewed_provider_request_id是人工证据冻结ID；provider_request_id仍是原始自动捕获ID，二者不混用。
  无结构时 history/recent 补 review_version=0、其余核实字段null，兼容旧台账。

POST 精确字段如下；amount=null 表示费用未知，currency 必须相应为null。

```json
{
  "request_id": "<一次待提交请求的稳定UUID>",
  "event_id": "<精确台账UUID>",
  "expected_version": 0,
  "expected_state": "unknown",
  "terminal_state": "error",
  "provider_request_id": "<供应商证明的请求标识>",
  "verified_amount": null,
  "currency": null,
  "evidence": {
    "source": "provider_request_record",
    "provider_host": "dashscope.aliyuncs.com",
    "reference": "<证据文件或供应商记录索引>",
    "sha256": "<证据文件的64位小写十六进制指纹>",
    "summary": "<人工核对结论，10到1000字>",
    "observed_at": "<UTC证据核对时间>",
    "terminal_confirmed": true,
    "zero_charge_confirmed": false
  }
}
```

state/version 来源于重新读取的精确row，不允许表单自行改写。终态只能 succeeded/error；
来源允许 provider_request_record/provider_billing_record/provider_support_record。
请求记录只能证明终态，费用必须有账单或客服证明，支持CNY非负decimal字符串最多12位小数，
最高10亿元。零费用还须明确 zero_charge_confirmed=true；费用未知不能勾选零扣款。
provider_host须与台账endpoint的host一致；已有provider_request_id时必须精确匹配。
review_version>0时还必须匹配该event最新且同版本审计冻结的evidence.provider_request_id。
原始自动ID为null也不能在补费用时改绑；缺审计、缺冻结ID或审计版本不一致均拒绝操作，精确读取也失败。
证据时间须为UTC、不早于调用开始、不晚于服务器当前时间60秒。
reference不包含控制字符，HTTPS索引不得包含userinfo/query/fragment，不访问该索引。
不在证据摘要、索引中放登录密钥、提示词或客户业务数据。

## 原子性、金额口径与迟到结果

共享 LOCK_ID=714102026，与准入同锁；SELECT FOR UPDATE锁住精确事件；
比较状态/核实版本，事务中更新终态、版本与核实金额，并追加审计后一次commit。
同request UUID、同操作者、同规范payload重放原结果；UUID被其他内容/操作者复用返回409。
不同请求竞争同版本只允许一次成功；审计写入失败整个事务回滚，不释放任何占用。
已确定终态不能换成另一终态；已有核实金额不能覆盖。本版本支持先核终态、随后另一次核费用。
人工错误的既定金额需要独立纠正流程审核，本端点不提供覆盖按钮。

原 estimated_amount、currency、pricing_version、rate_quote、token、provider_request_id 保留。
核实不补造usage或倒推价格。人工确认终态后并发占用结束，但 verified_amount=null 保持费用未核清。
三服务准入一致使用以下口径：

```sql
CASE WHEN review_version>0 THEN
    CASE WHEN verified_currency='CNY' THEN verified_amount END
ELSE estimated_amount END
```

已核实事件不得回退到旧估算或预留；只有仍requested的事件可用reserved_amount做金额预留。
历史核实金额未知仍跨日/月阻断相关金额预算，不能靠日历归零。
历史/成本/监控的unpriced及unresolved统一使用该口径；原估算仍单独展示。
known_amount是混合原估算与人工核实的**已知小计**，不是实际账单；
verified_amount为人工核实小计，estimated_known_amount为未核实事件估算小计；
estimated_amount维持全部原始估算已知时的原始汇总，actual_amount仍null。

原metering终态写入已有 `WHERE id=:id AND state='requested'`。
人工已改终态后迟到响应不覆盖人工结论；若metering先提交导致状态改变，人工请求因版本/状态冲突拒绝。
不改变业务任务状态，不重发模型、不修补供应商响应。任务与供应商调用状态须分别阅读。

## 具体新增SQL、权限及安装审查

实际文件：scripts/api_usage_review_schema.sql、scripts/api_usage_review_permissions.sql。
独立于各模块Alembic heads，无自动执行器。先完成现有metering/control安装审查。

| 对象 | 字段/约束 |
| --- | --- |
| api_usage_events增量 | review_version integer NOT NULL DEFAULT0 >=0；verified_amount numeric(24,12) >=0；verified_currency varchar(3)仅CNY；reviewed_at timestamptz |
| 台账核实约束 | 金额/币种同为null或同非null；review_version>0必须终态succeeded/error且reviewed_at非null |
| api_usage_review_audit | request_id uuid PK；event_id uuid NOT NULL FK到台账；actor_id bigint NOT NULL；request_hash varchar(64)小写hex；review_version integer>0；evidence jsonb object；before_value/after_value jsonb；created_at timestamptz默认CURRENT_TIMESTAMP |
| 审计唯一/索引 | UNIQUE(event_id,review_version)；(event_id,created_at)索引 |
| ACL | PUBLIC无权限；sem_runtime仅审计SELECT/INSERT，无UPDATE/DELETE；台账沿用SELECT/INSERT/UPDATE且无DELETE，无新增schema CREATE |

运行角色不是对象所有者、超级用户或拥有更宽继承权限时，才能证明上述append-only边界。
它不是抵抗数据库所有者篡改的密码学审计。实际列/类型/约束/索引/继承权限须人工核对，
helper的列存在检查不能取代安装审批。

仅供审核的目录/权限盘点SQL（不在本轮执行生产）：

```sql
SELECT table_name,column_name,data_type,udt_name,is_nullable,column_default,
       numeric_precision,numeric_scale,character_maximum_length
FROM information_schema.columns
WHERE table_schema=current_schema()
  AND table_name IN ('api_usage_events','api_usage_review_audit') ORDER BY table_name,ordinal_position;
SELECT conrelid::regclass,conname,pg_get_constraintdef(oid)
FROM pg_constraint WHERE conrelid IN ('api_usage_events'::regclass,'api_usage_review_audit'::regclass);
SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()
  AND tablename IN ('api_usage_events','api_usage_review_audit');
SELECT has_table_privilege('sem_runtime','api_usage_review_audit','SELECT') AS audit_select,
       has_table_privilege('sem_runtime','api_usage_review_audit','INSERT') AS audit_insert,
       has_table_privilege('sem_runtime','api_usage_review_audit','UPDATE') AS audit_update,
       has_table_privilege('sem_runtime','api_usage_review_audit','DELETE') AS audit_delete,
       has_table_privilege('sem_runtime','api_usage_events','DELETE') AS ledger_delete;
SELECT rolname,rolsuper,rolcreaterole,rolcreatedb FROM pg_roles WHERE rolname='sem_runtime';
```

安装顺序：

1. 三个独立发布单元先取共享07304cf8、501f5029，在各自检查中运行8项共享原生测试。
   不将整个SEM PR搬入SEO/GEO；核实API/UI可先发布但保持关闭。
2. 人工审核上述SQL及现有结构差异，记录对象owner与有效权限，保留正常备份恢复依据。
3. API_USAGE_REVIEW_ENABLED保持false；结构与权限由owner在审核窗口分别执行。
   每文件事务限lock_timeout3s、statement_timeout15s；无IF NOT EXISTS。
4. schema重复执行会整体失败回滚，不当成功；完整安装不重跑。
   正常失败事务整体回滚。人工造成部分安装则盘点差异、单独审核修复，禁止DROP/CASCADE或盲重跑。
   任一核实列半安装会让三服务准入在发请求前失败，即使没有预算也如此。
   审计表缺列/缺表时核实schema_pending、不可写，不影响原已完整的计量/预算读写。
5. ACL失败不撤销已提交schema；继续关闭核实。permissions可审核后重放以恢复目标grant/revoke，
   但必须验证真实继承权限、owner和role，不能只看脚本返回码。
6. 校验三服务实际Git提交、同库schema/角色、共享helper、全旧进程退出；前端整合到#646。
   三服务管理与计量已审核启用才考虑SEM核实开关API_USAGE_REVIEW_ENABLED=true。
   没有运行时证据时不宣称生产跨服务保护已成立。

回退：先关闭核实端点，不删除核实列/审计/已确认金额；继续保留三服务review-aware准入。
一旦存在review_version>0，不可回退到会忽略核实金额的旧准入实现。
应用功能回退沿既有独立发布链路；若必须回退共享保护，由负责人单独安排协调窗口与风险处置。
不删审计、不把未知金额改零、不关闭其他保护绕过旧占用、不修改资金开关。

## 健康固定读取合同

SEM snapshot只在命名全局超管授权后读取：

- SEO固定 `http://127.0.0.1:8020/api/v1/seo/workbench/onsite-ai/health`。
- GEO固定 `http://127.0.0.1:8010/api/v1/geo/workbench/onsite-ai/health`。

只传原调用者Bearer到固定loopback，不扩权、不接受客户URL、不跟redirect、trust_env=false。
两个请求独立并发、每个总3秒/HTTP2秒/响应最多32KiB，失败互不覆盖。
只投影schema1/module/UTC observed_at、worker和queue允许字段；错误体/额外字段不回显。

workers aggregate schema1/state=connected/partial/unavailable/not_connected、observed_at、rows、note。
row固定module/transport_state/module_observed_at/worker/queue；
transport_state=available/timeout/unavailable/unauthorized/invalid/not_connected。
aggregate connected只说明SEO/GEO健康端点读取成功，不证明整个服务/所有worker活跃。

worker固定scope=this_process或null、enabled bool或null、state active/degraded/stopped/unverified/not_connected、
verified、evidence仅{kind:local_tick,scope:this_process}或null、last_tick_at、
last_attempted/last_completed计数或null、last_error_code安全白名单worker_batch_failed或null。
只有明确verified、this_process、固定证据、最近120秒真实tick才保留active/degraded；
200/空队列不能证明心跳；读到旧于120秒或未来observed_at超过120秒的数据拒绝该行。
queue.state=available/schema_pending；queued/running/unknown及最早时间未知时null，绝不补零。
SEM没有该队列/heartbeat来源，固定not_connected/null，不制造cron/scheduler存活结论。
这个合同只覆盖站内AI durable队列，不代表所有SEO/GEO任务或整个服务集群。

## 可复现验收

复用 tests/test_platform_call_guards.py 的native fixture，仅localhost且DB名含test。
随机schema、实际SQL、两个独立池、MockTransport；不使用生产凭据，不调用付费供应商。

新增：tests/test_api_usage_review_basis.py（8），tests/test_platform_usage_review.py（21），
tests/test_platform_worker_health.py（15）。同一CI inventory必须执行并无skip/error，含原37/11/2套件。
首次本机实际18个CI同清单文件合计197 passed、0 skipped；首次新增44项包含在该总数内。
随后响应分块/深层JSON异常隔离修改单独复验15项健康测试通过。
集成复核再增加4项：自动ID为空时人工A终态后B补费用失败且台账/审计不变、同A成功，
审计缺失/冻结ID缺失/版本损坏均拒绝；核实套件现25项全部通过，CI强制最低25项。
覆盖四准入范围、终态/金额分离、跨期未知不释放、部分DDL零发送、同UUID重放与冲突、
两管理者版本竞争、真实metering迟到回写、审计故障整事务回滚、runtime只追加审计与台账无DELETE、
私有HTTP完整读写、证据关联/来源/零费用、健康旧心跳/redirect/大响应/超时/身份及错误隔离。

现用deepseek-chat与DashScope -0731的可信精确价格仍待核对；不猜价、不改模型、不发探针。
百炼账户余额接入不解决模型计费别名，也不是百炼独立消费明细。
生产保护、DDL与核实仍待对应发布/审批验收，测试通过不替代这些条件。

## 生产只读通信前提核对

2026-10-11从三个服务稳定MainPID环境内部比较：显式JWT_SECRET存在且有效签名键相同，
实际/proc/PID/cwd来源JWT_ALG均HS256，密钥选择helper与decode契约一致；
内部生成不输出的短时测试签名可被三配置验证。仅返回布尔，没有打印密钥/token/DSN/摘要。
这证明签名设置互认，不替代新健康接口上的实际命名账号权限验收，也不以crypto-key相同代替JWT证据。
SEO 127.0.0.1:8020和GEO 127.0.0.1:8010实际监听；新health路径均404，未上线/未验收。
未修改环境、重启服务、创建文件或执行生产SQL；脚本经SSH stdin只读执行。

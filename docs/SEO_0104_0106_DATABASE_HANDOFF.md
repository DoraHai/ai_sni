# SEO 0104 → 0105 → 0106 数据库执行交接

状态：供数据库负责人审批、执行；本文件及脚本不是执行授权。功能冻结，不重跑已完成业务写测试。复用正式 Alembic 迁移和现有健康检查，不使用本机种子、`create_all`、`stamp`、修补版建表 SQL 或新的迁移执行器。

**给统筹/DBA的简版：** 总控先部署兼容代码并确认维护窗口；DBA在备份恢复证明和独立迁移审批齐全后，逐段执行现有 `alembic upgrade 0105_seo_content_confirmations`、`alembic upgrade 0106_seo_content_messages`，每段授予第3节列出的新对象最小权限并跑第4节对应只读核验，第一段不过就停。新账号还须保留经审的现有登录/读取及行锁权限，不能只授新表权限。回传备份恢复证明、两段命令退出码、只读日志中的revision/对象/权限/行数及三服务健康结果；不带凭据或客户正文。无需发送文章、消息或开启AI/采集来验收建表。以下保留具体执行和失败处置规则。

2026-10-08 总控回传的只读生产核验：SEO current=`20261005T051003Z-d59d1a2c44ab`，健康 db/schema=ok、revision=`0104_seo_page_ai_tdk`；SEM RELEASE_COMMIT=`4d9c54f834296e155706748685e436859daf34d5`；GEO current=`20261005T051317Z-2aa079cbbeb7`；三个服务 db=ok。这是总控回传证据，本窗口未重复连接服务器。执行窗口仍须重新核对，0105/0106尚未获准生产执行。

本机对应Git源码核对：SEM `4d9c54f8`的`app/main.py`和GEO `2aa079cbbeb7`的`app/geo_main.py`健康入口均仅执行SELECT 1，没有revision白名单，因此这两个健康入口不会仅因版本字符串变为0106而拒绝；不能把它等同于所有业务或共享库授权已经通过验收。

## 1. 版本、审批和责任

| 内容 | 精确约定 |
| --- | --- |
| 起点 | `0104_seo_page_ai_tdk`，版本表恰好一行 |
| 第一段 | `0105_seo_content_confirmations`，父节点 `0104_seo_page_ai_tdk`，文件 `migrations/versions/20261007_0105_seo_content_confirmations.py` |
| 第二段 | `0106_seo_content_messages`，父节点 `0105_seo_content_confirmations`，文件 `migrations/versions/20261008_0106_seo_content_messages.py` |
| SEO 兼容实现 | 功能提交 `9f3037812d1efbe951c1b8056f0adc1346f64805`；发布包由总控固定最终 SHA、依赖和文件 SHA256，必须包含该实现及后续必要修复 |
| 先批准事项 | 总控批准部署健康检查兼容0104/0105/0106的SEO代码，并在数据库仍0104时验健康和既有读取 |
| 再批准事项 | 数据库负责人确认两段迁移、运行角色授权、备份恢复、维护窗口和失败处置；两段须同时在批准范围内，逐段执行/核验 |
| 分工 | 总控核验实际三服务运行版本、停止/恢复SEO运行和入口写；DBA操作备份、DDL与已批准授权；业务负责人另批客户计划/顾问分配/自动化开关 |

禁止 `alembic upgrade head`，避免共享分支新增迁移混入。禁止推断“0105已经上线”。若现场revision变更、多个revision、源码哈希不同、其他人正在迁移，立即停止重订计划。0105文件头部“未执行”是历史注释；本机完整迁移证据已存在，不代表生产已执行，不为修改该注释重写已核验的迁移文件。

## 2. 精确新增对象

两段仅增加结构及更新Alembic版本行，不回填顾问、不写服务计划、不改现有客户内容。五张表初次新建为空。

| revision | 表 | 序列 | 主键/唯一键 |
| --- | --- | --- | --- |
| 0105 | `seo_site_advisor_assignments` | `seo_site_advisor_assignments_id_seq` | id；`uq_seo_site_advisor_assignment_scope_user`(tenant_id,site_id,advisor_user_id) |
| 0105 | `seo_content_confirmations` | `seo_content_confirmations_id_seq` | id |
| 0106 | `seo_content_conversations` | `seo_content_conversations_id_seq` | id；`uq_seo_conversation_content`(content_asset_id) |
| 0106 | `seo_conversation_participants` | 无 | (conversation_id,user_id) |
| 0106 | `seo_content_messages` | `seo_content_messages_id_seq` | id；`uq_seo_message_request`(conversation_id,sender_user_id,request_id) |

五个主键索引均为 `<表名>_pkey`；三个唯一约束同名索引；另外11个索引如下，共19个索引。序列是bigint、自增1、不循环，必须属于相应id列，运行账号只需USAGE，无需setval权限。

```text
0105:
ix_seo_site_advisor_assignments_tenant_id
ix_seo_site_advisor_assignments_site_id
ix_seo_site_advisor_assignments_advisor_user_id
ix_seo_site_advisor_assignment_scope_active
ix_seo_content_confirmations_tenant_id
ix_seo_content_confirmations_site_id
ix_seo_content_confirmations_content_asset_id
ix_seo_content_confirmation_asset_latest
ix_seo_content_confirmation_exact_version
0106:
ix_seo_conversation_scope
ix_seo_message_conversation_id
```

0105有8个外键：assignment→tenants/seo_sites使用CASCADE，advisor_user→users为RESTRICT，assigned_by→users为SET NULL；confirmation→tenants/seo_sites/seo_content_assets为CASCADE，actor_user→users为RESTRICT。0106有6个外键且均RESTRICT：conversation→tenants/sites/content；participant→conversation/user；message的(conversation_id,sender_user_id)复合外键→participant。既有父表为`public.tenants/users/seo_sites/seo_content_assets`，不是其他schema的同名表。

六个CHECK：`ck_seo_content_confirmation_version`、`ck_seo_content_confirmation_decision`、`ck_seo_content_confirmation_actor_mode`、`ck_seo_participant_read_cursor`、`ck_seo_message_sender_kind`、`ck_seo_message_body`。列类型、空值、默认值、PK/UNIQUE、FK动作与索引按正式迁移源码及核验输出对账。

0106另有 `public.seo_reject_message_mutation()`：PL/pgSQL、返回trigger、非SECURITY DEFINER，抛23514，拒绝修改已有消息。两条启用的普通触发器仅属于`public.seo_content_messages`：

- `trg_seo_messages_append_only`：BEFORE UPDATE OR DELETE、FOR EACH ROW，tgtype=27。
- `trg_seo_messages_no_truncate`：BEFORE TRUNCATE、FOR EACH STATEMENT，tgtype=34。

没有新schema、扩展、角色或定时器DDL。已有同名表/序列/索引/函数不是“可以跳过”，必须停止对账，禁止DROP后重跑。

## 3. 账号与最小增量授权

DBA先指定两个不同的既有/经批准新建账号名称；这里不创建账号、不包含密码。迁移账号拥有本轮对象，具备数据库CONNECT、public USAGE/CREATE、四个父表REFERENCES、版本表SELECT/UPDATE；不需要SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS/REPLICATION。完整备份另用已批准备份身份，不为本轮DDL授予全库读取。

运行账号不得拥有新表、继承迁移对象所有者、获得public CREATE或管理角色。以下是**本批增量权限**，不是把空白账号接入整个SEO应用的完整角色方案；原登录、RBAC、租户模块、页面/任务等既有能力由总控保留经审核的权限，不执行全schema GRANT ALL/REVOKE ALL。

| 新表 | 应用权限 |
| --- | --- |
| seo_site_advisor_assignments | SELECT、INSERT、UPDATE(active,assigned_by,updated_at) |
| seo_content_confirmations | SELECT、INSERT；不授UPDATE/DELETE/TRUNCATE/TRIGGER |
| seo_content_conversations | SELECT、INSERT、UPDATE(id)，其中UPDATE只为现有FOR UPDATE行锁所需，接口不修改id |
| seo_conversation_participants | SELECT、INSERT、UPDATE(last_read_message_id) |
| seo_content_messages | SELECT、INSERT；不授任何列UPDATE或DELETE/TRUNCATE/TRIGGER |
| 四个新增序列 | USAGE；不授UPDATE/setval，不要求SELECT序列值 |

所有新表不授DELETE/TRUNCATE/TRIGGER。消息只追加触发器是额外保护，不能代替运行角色最小权限。首次创建触发函数时PostgreSQL通常默认PUBLIC EXECUTE；DBA可在批准的授权事务中撤销该新函数的PUBLIC EXECUTE。运行接口不直接调用触发函数，不需要额外EXECUTE；不要撤销其他已有函数权限。

**行锁容易遗漏**：消息API对users、seo_content_assets、assignment使用FOR SHARE，对conversation使用FOR UPDATE。PostgreSQL要求该表至少一个列的UPDATE权限。现有users登录维护权限通常包含UPDATE(last_login_at)；内容表保留已有经审写权限；新assignment上述三列UPDATE已足够。不能把运行账号误配成只有SELECT再宣称可发送。核验工具用`has_any_column_privilege`检查已有行锁前提。

DBA对上述白名单生成并审核精确GRANT。不要照搬示例账号名称；对象所有者/角色继承/列级权限均纳入检查。新增运行角色还需由总控单独安排连接配置、密钥注入和既有功能授权；本轮不得自动替换生产账号或修改配置。

## 4. 只读前后核验工具

`scripts/seo_confirmation_message_readiness.py`仅离线读取本仓库两份正式迁移，使用对象收集器复用其定义，生成psql只读SQL；不导入app配置、不读.env/凭据、不连数据库，也不会执行迁移、授权、种子、序列nextval或setval。

在固定发布目录生成三个核验文件，填写**非敏感**实际数据库名及两个角色名，使用空的新验收目录（工具拒绝覆盖）：

```sh
python scripts/seo_confirmation_message_readiness.py --revision 0104_seo_page_ai_tdk --database "$DB_NAME" --runtime-role "$RUNTIME_ROLE" --migration-role "$MIGRATION_ROLE" --output "$EVIDENCE_DIR/pre-0104.sql"
python scripts/seo_confirmation_message_readiness.py --revision 0105_seo_content_confirmations --database "$DB_NAME" --runtime-role "$RUNTIME_ROLE" --migration-role "$MIGRATION_ROLE" --output "$EVIDENCE_DIR/post-0105.sql"
python scripts/seo_confirmation_message_readiness.py --revision 0106_seo_content_messages --database "$DB_NAME" --runtime-role "$RUNTIME_ROLE" --migration-role "$MIGRATION_ROLE" --output "$EVIDENCE_DIR/post-0106.sql"
```

DBA使用已配置的受控连接服务，以**迁移账号**执行；连接服务名是需替换的非敏感示例，不在命令行拼接URL/密码，不启用shell xtrace：

```sh
psql -X -w 'service=seo_migration_checked' -v ON_ERROR_STOP=1 -f "$EVIDENCE_DIR/pre-0104.sql" > "$EVIDENCE_DIR/pre-0104.log"
```

迁后相同方式分别执行post-0105.sql和post-0106.sql。SQL使用REPEATABLE READ READ ONLY、15秒检查超时、3秒锁超时，失败停止且不修改数据；连接关闭回滚未结束的只读事务。缺失对象、版本行数量错误、错误owner/类型/默认值/主键/唯一键/外键/索引/触发器/函数或权限均拒绝；缺表导致SQL直接报错也按未通过处理。CHECK验证名称/数量/validated并输出完整表达式，**DBA仍须逐项比对6条CHECK表达式与源码**，不能仅凭同名约束判定含义正确。

脚本还返回本轮新表行数、新计划开关计数、本批在途任务分组及父表锁信息，不输出客户正文、消息正文、SQL查询文本或密钥。这些是需要人工签核的业务/锁等待前提；`readiness_ok=true`不代表开关获授权或锁永远空闲。

迁移使用asyncpg，**不能依赖libpq的PGOPTIONS给Alembic设置会话参数**。执行前DBA保证Alembic连接身份/数据库的有效search_path仅public，继承有效lock_timeout为1–10000ms、statement_timeout为1–300000ms（建议5秒/120秒）；脚本在覆盖自身检查超时前检查原会话设置。若原值0/路径不符，停止，由DBA另行审核限定到迁移角色/数据库的设置，不能由工具私自ALTER ROLE。psql服务与Alembic必须指向同一DB/角色且没有各自覆盖search_path/超时；现场核验由DBA负责。脚本退出成功不是对另一套连接配置的证明。

工具自动检查目标对象在当前版本的存在/缺失。版本已为0105且有正式执行记录时，应跳过pre-0104，先执行post-0105；不能把0104期望强行套用已完成的第一段。

## 5. DBA窗口执行清单

1. 固定兼容发布SHA、两份迁移及核验工具SHA256；审阅唯一迁移图和父节点。兼容SEO先部署，在原0104健康通过。新确认接口503、消息503是结构未就绪的预期状态，不应借机开启功能。
2. 总控按已批准维护安排停止SEO业务写入、调度和后台进程，并协调共享数据库其他模块写入/备份一致性；迁移中不能让新代码在0105落地瞬间启动在途任务。暂停/恢复服务是总控操作，不在只读工具内执行。
3. DBA验证目标DB、迁移/运行角色、public路径、超时和父表锁；执行pre-0104，检查所有未来对象不存在、无未批准开关/任务或顾问初始化计划。任何不一致停止。不要终止不明会话来抢锁。
4. 使用既有备份流程做共享库一致性备份，保留角色/ACL、schema、数据和版本行；记录时间、备份位置、校验和、WAL/PITR可恢复点和保留期。若使用pg_dump，使用独立受控备份连接和`--format=custom --file=新路径`；用pg_restore --list核对可读，再按既有流程在隔离目标做恢复可用性检查。只有dump退出0/文件非空不等于恢复已验证。未完成恢复证明停止执行。
5. 在已审核发布包、已由DBA注入迁移身份的环境，用**现有**入口执行：`python -m alembic upgrade 0105_seo_content_confirmations`。本文件不提供/读取DATABASE_URL；DBA必须确认配置确实使用迁移账号，不能沿用应用账号猜测执行。
6. 第一段成功后由DBA执行已批准的0105精确授权，再跑post-0105，保存退出码/日志。新两表应0行；确认版本恰好0105，0106未来对象仍不存在。审核所有CHECK/FK输出。第一段核验不通过时停止，不能继续第二段。
7. 执行 `python -m alembic upgrade 0106_seo_content_messages`。再执行0106已批准精确授权，跑post-0106。新三表应0行，既有0105数据保持；核对三个对象集合及角色权限、函数和两条触发器。**不发送测试消息、不生成顾问分配、不补客户确认或人工发布记录**来让检查变绿。
8. 总控恢复兼容SEO的受控只读访问（新自动化仍须按下一节关闭/未授权），核对实际运行SHA、SEO schema=ok/0106和必要结构、SEM/GEO db健康，以及已有获准客户/站点的只读接口。健康检查只证明对应检查通过，SEM/GEO的db=ok不能代替其业务兼容性签核。
9. 对账备份版本、迁后版本、对象/权限、空表行数、既有数据监控及维护窗口写入记录。数据库负责人和总控签字后结束窗口。逐客户顾问分配、确认、自动草稿、采集/发布开通是后续独立授权，不属于建表验收。

## 6. 首次上线默认状态（只核本批新增逻辑）

`_service_plan_payload`对content_cycle_enabled、content_ai_enabled、website_cycle_enabled、monitoring_cycle_enabled、report_cycle_enabled仅在JSON值为true时开启；缺失均false。计划status缺失显示active，但不等于周期/AI开关打开。AI授权人/时间缺失为空；自动草稿还需当前活动顾问分配、用户权限、资料/关键词及显式AI授权。正式迁移不插入上述任何数据。

`run_content_workflows`和`run_service_workflows`复用schema_ready，未0105不工作；到0105/0106后还要求活动站点和顾问分配。新建周期任务要求对应开关显式true；**已有open/in_progress任务仍可能被推进，不受“新建周期关闭”充分保护**。已有claimed草稿也有恢复分支（仍重新验证授权）。核验工具检查content_delivery/site_diagnosis/ranking_followup/monthly_report在途数，DBA/总控核实授权来源；不能仅看开关false即恢复任务运行。初次0105空assignment表形成额外门槛，但不能为恢复页面可用性批量回填顾问。

现有全局`seo_scheduler_enabled`/`seo_external_actions_enabled`默认true，`seo_page_capture_enabled`默认false；因此不能称“系统默认全部不自动运行”。首次兼容部署及建表窗口，由总控确认有效运行配置禁用新增工作或保持SEO进程停止，未经批准不改配置/服务计划。发现存量显式true、活动任务或未来顾问初始化会使任务启动时，停止放行并单独确认逐客户范围。不能以合并代码或建表审批替代AI、采集、发布授权。

本批内容worker不调用发布供应商，只在已有批准/发布事实之后推进页面证据；页面capture仍受开关和操作权限限制。人工消息不改变审核/确认/发布状态；新表和消息API不能自动构造“发布成功”或“搜索效果提升”。

## 7. 失败停止与回退

- 每段非零退出、断线、锁/语句超时或核验失败，立即暂停后续命令和SEO业务入口，保留脱敏日志。`migrations/env.py`在PostgreSQL事务中执行单次upgrade；网络中断时提交结果可能不确定，不能只凭客户端报错认定回滚。
- 只读核对实际revision和对象：仍0104且无0105对象可按批准计划排障；完整0105则留在0105并先验第一段；完整0106则验第二段；混合对象、异常版本行或不完整事务证据交DBA处理。不自动重试CREATE、不stamp、不删表补齐。
- 数据库到0105时只能运行认识0105的兼容包；到0106时只能运行认识0106的包。生产当前旧SEO0104包、以及白名单只到0105的76ce5920均不能作为0106上的直接回退版本。预先保存同样兼容0104/0105/0106且经过核验的代码回退包；回退代码不能暗中降库。
- 0105/0106源码downgrade会删除新表，0106还会删除只追加消息记录。即使曾在本机验证，也不得在生产自动downgrade。优先维持已提交schema并修复/恢复兼容代码；若必须恢复数据库，另批全共享库恢复/PITR方案，明确SEM/GEO在备份点之后写入的损失、停机及消息/确认历史处置，不把整库恢复当成只回滚SEO。

本轮验证边界：核验生成器只做离线对象/只读性测试；没有读取凭据、生成生产授权、执行该SQL连接生产或重复业务测试。生产SQL实跑及两段完整审批/备份恢复证明仍由DBA完成。此前本机真实迁移、276项回归及25+3消息对账继续引用`SEO_LOCAL_ACCEPTANCE.md`与`SEO_AUTOMATION_PROGRESS.md`，不重复计算。

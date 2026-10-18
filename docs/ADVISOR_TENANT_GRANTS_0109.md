# 0109 受审执行包：草稿，不可合并直到用户批准

**不可合并：合并即自动发布。迁移本身不由发布 workflow 执行。**

E2 基于 E1，PR base 为 codex/advisor-mt-seo-guard-20261018。
必须先由用户批准 E1 合并并发布，再将本 PR base 改为 codex/production-seo。
production-seo-deploy.yml 仍只打包 migrations，MANIFEST migration=not-run；head 断言改为 0109。

只新增方案 3.2 的 advisor_tenant_grants。Identity 不需序列授权，默认 ACL 在同事务撤回；
sem_runtime 只授 SELECT/INSERT/UPDATE，无 DELETE/DDL/角色/其他表权限增量。
新表触发器只允许活动行撤销，授予字段不可改、已撤销行不可再更新；重授予必须新行。
触发器函数的 PUBLIC/sem_runtime EXECUTE 默认授权也收回，不以运行账号执行函数授权换取保护。
角色不存在仅 NOTICE 并跳过 ACL，不创建角色；发现继承得到额外权限时异常终止，交用户另审。

回填沿用仓库独立 SQL 执行包的方式，位于 scripts/advisor_tenant_grants_backfill.sql，
不在迁移中自动导入。用户批准首次导入窗口，冻结账号/角色/名单编辑后由受控 owner 执行。
非法角色权限类型先阻断；按方案 7.2 predicate（不按账号启用/锁定筛掉历史绑定），
NULL/不存在客户不回填，NOT EXISTS 任一用户历史阻止撤销后重跑复活，重跑新增 0。
仅在经核准首次窗口执行，完成后封存，不能作为定时修复作业。

docs/ADVISOR_TENANT_GRANTS_ACL_AUDIT.sql 包含方案 8.3 两条核对 SQL：
方案示例的 defaclobjtype 为 PostgreSQL 内部 char，拼接时显式 ::text 消除运算符歧义；只修 SQL 类型转换。
新表以外权限快照前后差集为空；新表只有 SELECT/INSERT/UPDATE 为 true；owner 不是 sem_runtime。
身份序列的 USAGE/SELECT/UPDATE 和触发函数 EXECUTE 不得出现 runtime 新授权。
生产 owner/权限继承/默认 ACL/数据库当前 revision 仍须 DB 负责人按审批窗口核实，本次未连接任何远程库。

本机无 postgres/docker 时，执行隔离环境下的 Alembic 0108:0109 --sql 和静态测试；
CI migration-validation 的临时 postgres:16 service 执行原生约束、不可逆撤销、回填、ACL 测试。
测试绝不复用生产连接串；只接受 loopback、数据库名 test、无额外 URL 参数。

回退走已发布且兼容 0109 的 guard 代码，关闭入口、保留表/历史/ACL；downgrade 明确 raise，
不 drop、不清历史、不 stamp、不重新启用旧 via。SEM API/前端/GEO guard 都就绪且用户批准后才能启用。

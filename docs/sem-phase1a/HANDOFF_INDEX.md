# 阶段1a第四刀续做交接索引（task11b）

- 当前契约、清理锁/数据库完整性约束、未挂载的管理API、真实会话权限与挂载阻塞：[README.md](README.md)第四刀章节。
- 范围A：`app/sem_phase1a/postgres_store.py`、`router.py`；`tests/test_sem_phase1a_slice2.py`、`sem_phase1a_session_fixture.py`。
- 管理服务/路由：`app/sem_phase1a/grant_management.py`、`grant_router.py`；默认复用现有require_admin，仅显式测试app挂载，`app/main.py`未改。
- 新增迁移：`migrations/versions/0078_sem_phase1a_grants.py`，接0077；复合账户tenant约束、generation与事务审计，只加不删，无生产upgrade/权限扩张。
- 新增测试：`tests/test_sem_phase1a_slice4.py`；真实会话管理检查：`tests/sem_phase1a_management_checks.py`（由隔离session夹具调用）；迁移契约更新唯一head。
- review13_out.md修复：README历史cleanup/schema标明第四刀取代；slice3空phase1a schema测试实际链式升级0077→0078并核对generation/审计表；真实HTTP验证API Key超管通过require_admin后仍被管理服务403拒绝、无绑定/审计变化；第一刀业务异常断言收紧为ShadowError。生产挂载与0078生产巡检/索引窗口仍须另行授权，详见外部交接“review13_out.md修复”节。
- review14_out.md修复：授权管理三个端点及直接服务在同事务锁定/核验SEM模块，suspended/closed/过期/缺失均固定403，补两类管理员HTTP/服务及无绑定/审计变更回归；README明确审计仅服务写入的SOP和历史cleanup口径。生产挂载、0078运维与原生PG管理路径扩展的范围说明见外部交接“review14_out.md修复”节。
- review15_out.md修复：原生PG补跨租户修改account_id拒绝与回滚断言；预览上传前的读取拒绝返回读取权限文案，并验证附件尚未读取；README明确cleanup自有连接/事务，与apply以行锁协调。范围外重要项及历史迁移说明见外部交接同名节。
- 完整本刀交接/逐步状态：`D:\SNIPERS国内版\梳理-2026-10\sem-entry-20261027\PHASE1A_SLICE4_HANDOFF.md`、`status11.md`；PLAN改前备份`PLAN.v10.md`保留。
- 分支`sem-phase1a-shadow-slice4-20261029`，Draft目标slice3，叠#821；最终提交/PR/本地与CI测试数/原生PG执行证据见外部交接与status11。
- OSS：`oss://snipers-video-transfer/diag-20261029/sem-phase1a-slice4/`；PLAN、交接、status及此README/索引最终逐份回读SHA-256，status自身hash独立记录避免自引用。
- 下一刀由用户决定阶段0来源/附件生产持久化范围，再审挂载与顾问门禁。本刀结束即停，不联系任何人，不请求reviewer/assignee，不合并/部署。

---

# 阶段1a第三刀历史交接索引（task10）

- 当前契约、存储/会话适配、仍未挂载的真实会话门禁： [README.md](README.md)。
- 第三刀实现：`app/sem_phase1a/principals.py`、`production_principals.py`、`postgres_store.py`、`service.py`、`router.py`、`excel.py`。
- 新增迁移：`migrations/versions/0077_sem_phase1a_shadow.py`；仅代码，未在生产执行。
- 新增合成测试：`tests/test_sem_phase1a_slice3.py`；真实JWT隔离夹具：`tests/sem_phase1a_session_fixture.py`。
- review11修复：生产依赖保留既有HTTP错误、两种适配器resolve拒绝空绑定、第一刀API复用`tests/sem_phase1a_auth_fixture.py`；完整测试要求和账户绑定运营SOP见README，逐项修复/建议与最终验证见外部交接新增的“review11修复轮”章节。
- 样例：[授权](samples/slice3-auth.internal.json)、[演练复核](samples/slice3-review.internal.json)、[重启/重放](samples/slice3-persistence.internal.json)、[内部Excel](samples/slice3-review.internal.xlsx)。
- 完整本刀交接与逐步状态：工作目录 `D:\SNIPERS国内版\梳理-2026-10\sem-entry-20261027\PHASE1A_SLICE3_HANDOFF.md`、`status10.md`；计划改前备份PLAN.v9.md。
- 封存副本：`oss://snipers-video-transfer/diag-20261029/sem-phase1a-slice3/`，含PLAN、交接、状态及上述关键样例；最终提交/PR/CI/SHA-256见status10。

本刀结束即停。仅演练，不可执行、不可上线；未联系审查人、不请求reviewer/assignee、不合并、不部署。后续先审真实顾问路径门禁与账号绑定的授权管理/留存，再决定是否进入下一刀。

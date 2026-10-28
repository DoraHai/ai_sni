# 阶段1a第三刀交接索引（task10）

- 当前契约、存储/会话适配、仍未挂载的真实会话门禁： [README.md](README.md)。
- 第三刀实现：`app/sem_phase1a/principals.py`、`production_principals.py`、`postgres_store.py`、`service.py`、`router.py`、`excel.py`。
- 新增迁移：`migrations/versions/0077_sem_phase1a_shadow.py`；仅代码，未在生产执行。
- 新增合成测试：`tests/test_sem_phase1a_slice3.py`；真实JWT隔离夹具：`tests/sem_phase1a_session_fixture.py`。
- 样例：[授权](samples/slice3-auth.internal.json)、[演练复核](samples/slice3-review.internal.json)、[重启/重放](samples/slice3-persistence.internal.json)、[内部Excel](samples/slice3-review.internal.xlsx)。
- 完整本刀交接与逐步状态：工作目录 `D:\SNIPERS国内版\梳理-2026-10\sem-entry-20261027\PHASE1A_SLICE3_HANDOFF.md`、`status10.md`；计划改前备份PLAN.v9.md。
- 封存副本：`oss://snipers-video-transfer/diag-20261029/sem-phase1a-slice3/`，含PLAN、交接、状态及上述关键样例；最终提交/PR/CI/SHA-256见status10。

本刀结束即停。仅演练，不可执行、不可上线；未联系审查人、不请求reviewer/assignee、不合并、不部署。后续先审真实顾问路径门禁与账号绑定的授权管理/留存，再决定是否进入下一刀。

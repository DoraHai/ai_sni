# SemTask 独立迁移源包：仅本地演练

候选 `0095_sem_tasks` → 父节点 `0094_seo_qa_batches`。生产迁移尚未批准。
历史来源固定为 `4e83611aabc8c3d9bb6ecee1a6aff37a2fbfbe21`，
`SOURCE_LOCK.json` 固定 111 个历史迁移和 5 个迁移导入所需辅助文件的 SHA-256。
历史从 Git blob 读取，不受工作区换行符或当前应用代码影响，不修改任何历史文件。
来源提交是候选迁移图的源码依据，不代表已查明生产历史执行提交。

构建需本地已有该 Git 对象；缺失时失败，不回退到移动分支。浅克隆环境需先单独取得并
核对该确切提交。本工具不自动 fetch，不连接服务器，也不读取应用 `.env`。
从已审核工作区用隔离 Python 运行（将 `<新目录>` 替换为尚不存在的本地路径）：

```text
python -I -B ops/sem-task-migration/bundle.py build <新目录>
python -I -B ops/sem-task-migration/bundle.py verify <新目录>
python -I -B ops/sem-task-migration/bundle.py plan <新目录>
```

产物含 118 个源码文件及 MANIFEST.json。核验完整文件集合、每个摘要、来源 SHA、唯一头和
单步计划；拒绝符号链接、额外文件、摘要不符。MANIFEST 是完整性清单，不是数字签名；
源包和构建工作区都必须来自审核提交，存放于仅操作者可写的目录，验证期间禁止并发修改。
不应把摘要校验宣称为防御有权限同时篡改工具和源包的安全边界。

## 真实本地测试

仅允许本机临时 PostgreSQL，**不得使用 SSH 隧道、生产代理或转发端口**。
专用环境变量 `SEM_TASK_MIGRATION_TEST_DATABASE_URL` 必须指向
`postgresql+asyncpg://<本地测试用户>@127.0.0.1:<显式测试端口>/sem_tasks_migration_test`。
禁止使用生产凭据。测试数据库需预先存在，必须确认是可丢弃的本地实例。

```text
python -m pytest -q tests/test_sem_task_migration_bundle.py
```

测试创建并清理自己随机命名的 schema；用最小前置结构模拟 0094，再调用实际 Alembic。
此 fixture 不是生产恢复副本或完整 SEO Schema，不重放历史迁移。
未设置变量时实际 Alembic 用例明确跳过；设置后源提交缺失或连接失败必须测试失败。
本次没有给 CI 增加数据库/Alembic 任务。

底层 `local-upgrade` 只接受专用本地库、随机测试 schema、单行 0094，固定目标 0095；
不接受 `head`、任意目标、downgrade、stamp，也没有生产运行模式。
同一事务锁定版本表、检查对象冲突、执行迁移、核对版本；锁等待 1 秒、语句超时 10 秒。
测试故障注入在建表后、建索引前触发，检查表/序列/索引和版本更新一并回滚。

## 生产前仍需独立审核

1. SEM/SEO/共享迁移负责人审核候选图、历史证据缺口及完整当前结构对账。
2. SEO #369 加入该目标的兼容测试，独立获批后先部署兼容版。
3. 审核正式生产执行入口（此处未提供）、备份/PITR、权限、并发变更管控和失败处理。
4. 单独明确批准迁移；SemTask 开关及应用重启另行批准。

不修改现有发布 workflow，不让普通应用发布运行迁移；普通发布仍为 `migration=not-run`。

# 0111 离线迁移包（待审核，不自动执行）

本包从共用链 `0110_distribution_inbox -> 0111_geo_autopatrol` 生成，禁止使用退役 GEO 链 0075 对生产升级。共用链 PR 必须先经独立审核合入并成为未来迁移的共同历史；本任务仅开 Draft PR，不执行迁移或发布。三服务共用同一库和 alembic_version，不创建第二张版本表。

## 文件和逐类语句说明

- precheck.sql：只读事务，固定 public；SELECT 检查 sem_app、sem_prod、唯一版本 0110、两张旧表为普通表、全部17个新字段及所有新对象不存在；列出旧表行数；任何 false/NULL 通过除零使执行停止。没有业务写入或序列取值。
- upgrade-0111.sql：Alembic 原样离线输出（含 BEGIN/COMMIT）。DO 检查两张旧表；LOCK 保持检查到修改间结构稳定；DO 拒绝任一已存在的新字段、表、索引或序列；15条 ALTER TABLE 向 settings 加默认/可空列，2条向 runs 加可空列；CREATE UNIQUE INDEX 只约束非空 auto_day；CREATE TABLE 新审计表（BIGSERIAL 自带序列、主键、tenant 外键）、CREATE INDEX 客户事件顺序索引；CREATE TABLE 北京日预算表及主键；UPDATE 版本号为 0111（只改 alembic_version，不回填业务行）；COMMIT。
- apply-0111.psql：ON_ERROR_STOP；BEGIN；设置5秒锁等待/300秒语句时限和 public；锁版本表，DO 再次断言用户、库、唯一版本；逐字嵌入上项除外层事务以外的 SQL；事务内 SELECT 校验新版本、17字段、两新表、部分唯一索引及列顺序、审计索引、两个主键、运行角色每项 DML/序列权限、旧设置默认值和旧 run 无日占位；全部通过才 COMMIT。失败须退出并让事务回滚，禁止跳过检查或单独 stamp。不得将 upgrade 文件与 apply 文件重复执行。
- verify.sql：只读事务重做事务内校验。仅在迁移完成且业务功能未启用时使用：这里所有 settings/runs 都是本次旧行；启用后应有非 legacy 状态和 auto_day，此立即验收条件不再适用。settings 当前0行、runs 11行来自任务给定只读事实，本任务未查询真实库。
- SHA256SUMS：包内五个文件的 SHA256；不自包含、不含自身。

## 默认权限及不一致处理

不含任何权限变更。新对象由 sem_app 创建，依赖其既有默认权限；不假设默认权限实际正确，必须逐项验证 sem_runtime 的 SELECT/INSERT/UPDATE/DELETE、事件序列 USAGE/SELECT/UPDATE。PostgreSQL 权限函数的逗号列表仅表示任一权限，因此这里逐项 AND，确保全部成立。预算表按日期主键，无自增序列。任何权限缺失都会使 apply 在 COMMIT 前失败并回滚；禁止临时补授权。需要另行审核后处理。

与0095的共同点是共用链收编独立GEO链的等价schema、不搬运整条分支。0095有已核实的线上精确既有形状，允许完全一致时接纳；0111没有已执行0075的证据，因此严格要求全部不存在，完整/部分既有状态也拒绝，不自动猜测或接纳。此选择允许离线输出与实际迁移执行相同的前置检查。新增内容的DDL校验值与GEO 0075相同，迁移测试冻结此契约。所有应用回退保留schema，0111降级被明确拒绝。

## 锁影响

settings 当前0行、runs当前11行：常量默认值的新增字段由现代PostgreSQL使用元数据默认值，不执行猜测历史回填；两个可空字段无需业务更新。ALTER/显式LOCK取得ACCESS EXCLUSIVE，期间相关表读写被短暂阻塞；普通唯一索引扫描11行，不使用CONCURRENTLY以保持单事务。版本表EXCLUSIVE锁串行化迁移，普通SELECT仍可读。新表创建含tenant外键会对被引用tenants取得相应关系锁，短暂阻塞冲突DDL/写操作；等待任一锁超过5秒或单条语句超过300秒即失败，事务回滚。小行数不能保证无阻塞，获授权执行者仍应选择低流量时段并检查前置结果。本任务不连接数据库，不观测当前锁或权限。

生成方式：在清空继承的业务环境、禁用dotenv、仅写入合成占位配置的进程里，调用标准 Alembic `upgrade 0110_distribution_inbox:0111_geo_autopatrol --sql`。仅离线生成，不建立数据库连接。apply中的生成体与该输出逐字比对；仓库docs副本与release目录逐文件比对。

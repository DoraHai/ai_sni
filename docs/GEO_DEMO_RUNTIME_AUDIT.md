# GEO 独立 Demo Runtime 与空库迁移审计

## 结论

GEO 演示应运行在独立 demo runtime 和独立 PostgreSQL database，不加载生产业务库。当前
`codex/production-geo` 的迁移 head 是 `0074_geo_ticket_assignment`。空库可以从迁移图的单一 base
`0001_initial` 向该 head 升级，但这不是 GEO-only 迁移：它会创建 SEM、共享认证、SEO 和 GEO 的完整
空 schema。现有 CI 的 `ops/run_geo_checks.py --postgres` 使用 `MetaData.create_all` 创建 GEO 测试子集，
没有验证 `alembic upgrade head`，因此独立 demo DB 首次迁移仍需要数据库负责人在一次性空库中预演。

协调决定以 `1f46fab9` 为准：PR `#504` 保持 Draft，不合并、不部署，本轮不建库、不跑迁移、不实现
数据 apply。

## 迁移依赖

迁移图只有一个最终 head，但中间有多次分支和 merge：

- `0001_initial` 创建共享 `tenants`，同时创建百度账户与审计表；
- `0010_users` 创建共享用户，并外键到 `tenants`；
- `0016_custom_roles` 创建和填充系统角色，把用户迁移为 `role_id`；
- GEO 从 `0035_geo_audits` 开始，内容、回答、引擎、发布、巡检、业务层级和周指标依次建立；
- `0055_merge_geo_platform` 合并 GEO 与 OAuth/平台分支；
- `0064_merge_geo_sem_heads` 合并 GEO 与 SEM/SEO 分支；
- `0066_module_workspaces` 创建共享 `tenant_modules`、SEO site、GEO project，并修改系统角色权限；
- `0072_merge_login_seo` 再次合并共享登录与 SEO 发布分支；
- `0073_geo_schema_repair` 假设先前 GEO 表存在并做幂等修复；
- 当前 head `0074_geo_ticket_assignment` 增加 GEO 待办负责人和期限。

因此不能从 `0035` 或任一 GEO revision 直接 stamp 后升级；那会跳过 `tenants/users/roles` 以及多个历史
GEO 父表，并可能复现生产曾出现的 stamped-but-DDL-missing 问题。独立空库必须运行仓库完整迁移链，
并在升级后核对单一 head、所有共享基础表和全部 GEO 表。

迁移依赖 PostgreSQL 特性，包括 JSONB、部分索引和序列修复 SQL。没有发现必须预装的 PostgreSQL
extension。迁移进程仍会加载共享 `Settings`，所以除 `DATABASE_URL` 外还必须提供 demo-only 的
`BAIDU_*` 占位值、`CRYPTO_MASTER_KEY_B64`、`ADMIN_API_KEY` 和 `JWT_SECRET`；这些不得复用生产值，
也不应拥有外部系统权限。

## 空库预演步骤（仅数据库负责人执行）

1. 新建一次性 PostgreSQL database 和只能访问该库的 owner/migrator；确认该账号无法连接生产库。
2. 使用待部署的完整协调分支，而不是单独的 GEO release archive；先执行 `alembic heads`，必须只有
   一个 head。当前 GEO 基线预期 `0074_geo_ticket_assignment`，协调分支若已有更新则以协调分支 head
   为准，禁止手工 stamp。
3. 在空库执行一次 `alembic upgrade head`，记录起止 head、耗时和错误，不插入演示夹具。
4. 运行 schema 核对：共享 `tenants/users/roles/tenant_modules` 存在；GEO 模型涉及的表、列、外键和
   唯一约束均存在；系统角色 seed 数量符合迁移定义。
5. 再执行一次 `alembic upgrade head`，必须为 no-op。
6. 删除整库并重新创建，再完整执行一次，以证明恢复路径不是依赖首次残留。

当前不能声称空库迁移已通过；CI 覆盖的是模型子集，不是 Alembic 全链。

## Demo runtime 必须关闭的进程和动作

当前 `app.geo_main` 启动时会无条件：恢复异步内容任务、恢复巡检、启动 GEO scheduler、启动 followup
supervisor，并每 60 秒运行 stale reconciliation。现有配置没有关闭这些行为的总开关。因此仅在环境
文件里写 `false` 尚不会生效，不能直接把 `app.geo_main:app` 当作安全 demo runtime 启动。

建议 demo 环境契约如下；在 `geo_main` 接入这些开关或增加 scheduler-free demo entrypoint 之前，
服务保持不启动：

```dotenv
APP_ENV=demo
GEO_DEMO_RUNTIME=true
GEO_SCHEDULER_ENABLED=false
GEO_FOLLOWUP_SCHEDULER_ENABLED=false
GEO_STALE_RECONCILIATION_ENABLED=false
GEO_STARTUP_RECOVERY_ENABLED=false
GEO_ASYNC_WORKER_ENABLED=false
GEO_PATROL_EXECUTION_ENABLED=false
GEO_MODEL_EXECUTION_ENABLED=false
GEO_CONTENT_GENERATION_ENABLED=false
GEO_PUBLISHING_ENABLED=false
GEO_OAUTH_ENABLED=false
BAIDU_WRITE_DRY_RUN=true
CHINAZ_API_ENABLED=false
SEO_RANK_SCHEDULER_ENABLED=false
```

所有外部模型、搜索和页面性能 Key 必须为空，包括 `DASHSCOPE_API_KEY`、`DEEPSEEK_API_KEY`、全部
`GEO_*_API_KEY`、`CHINAZ_*_API_KEY` 和 `PAGESPEED_API_KEY`。数据库中的引擎、AI 设置、发布渠道和
巡检设置继续保持离线夹具定义的 disabled 状态；channel account 和 publication 必须为空。

共享 Settings 当前要求若干百度和加密配置非空。demo runtime 只能使用无权限的 demo 占位值及独立
demo 加密/JWT/admin secret，不能读取生产 EnvironmentFile，也不能复用 `/opt/sem-backend/.env`。
systemd 服务必须使用独立工作目录、独立 env 文件、独立用户和独立端口。

## Loader fail-closed 草案

`app/geo/demo_database_guard.py` 只解析并校验配置，不连接数据库。未来 loader 在建立连接前必须全部
满足：

1. `APP_ENV=demo`，且确认串精确为 `LOAD_GEO_DEMO_ONLY`；
2. `GEO_DEMO_DB_HOST`、`GEO_DEMO_DB_NAME`、`GEO_DEMO_DB_USER` 都非空且包含 `demo`；
3. `DATABASE_URL` 只能是 PostgreSQL，hostname、database、username 与三项白名单逐字匹配；
4. URL query 只允许 `ssl`/`sslmode`，拒绝 `host`、`service`、`options` 等目标覆盖方式；
5. 上述 scheduler/worker/巡检/模型/生成/发布/OAuth 开关全部处于关闭状态；
6. 所有外部凭据为空；
7. 校验结果只返回 driver、host、port、database、username，不回显 URL 或密码。

任一条件不满足即抛出 `DemoDatabaseGuardError`。草案没有数据库 import、连接、迁移、apply、seed、
cleanup 或网络调用。

## 仍需确认

- 数据库负责人：独立数据库/实例的最终 hostname、database name、loader/migrator/runtime 三类账号及
  权限；完整协调分支的最终 Alembic head；空库两次迁移和整库重建结果。
- 服务器负责人：scheduler-free 入口还是在 `geo_main` 接入开关；独立 systemd/container、端口、
  EnvironmentFile、健康检查、日志和回滚目录；demo 服务不得读取生产 secrets。
- 跨模块负责人：认证服务是否同库部署、演示普通用户和角色如何 seed、前端如何固定显示全虚拟标识。

上述信息确认前，PR `#504` 保持 Draft，不实现或执行 loader apply。

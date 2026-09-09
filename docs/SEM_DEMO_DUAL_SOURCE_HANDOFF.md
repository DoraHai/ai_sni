# SEM 独立演示库只读适配交接

## 边界

生产账号、角色、菜单权限、SEM 模块资格和服务端绑定都从 `sem_prod` 校验。只有配置在
`SEM_DEMO_PRINCIPAL_TENANT_IDS` 中的生产租户身份进入演示路由；这些身份缺少唯一有效绑定、
绑定表版本不符、演示库不可达或任一安全校验失败时返回 503，不回退读取生产业务数据。

客户端的 tenant、header 和 query 不能选择数据库。`tenant_id` 只用于验证请求仍属于已认证的
生产租户；服务端再用 `demo_tenant_bindings.demo_tenant_id` 进行内部查询。响应顶层
`tenant_id` 会恢复为生产租户 ID，避免暴露内部演示租户标识。

演示身份只允许以下 GET：

- `/api/v1/auth/me`
- `/api/v1/auth/modules`
- `/api/v1/auth/tenants?module=sem`
- `/api/v1/dashboard/cockpit`
- `/api/v1/keywords/cockpit`
- `/api/v1/keywords/cockpit/{keyword_id}`
- `/api/v1/search-terms/cockpit`

`/dashboard/today`、分析报告、月报、导出、投放、同步、OAuth、AI、任务写入以及其他路由均被
服务端门禁拒绝。scheduler、worker、百度写回和 AI 模块不导入演示库会话工厂。

## 启用前提

启用配置必须一次性完整提供：

- `SEM_DEMO_DATA_SOURCE_ENABLED=true`
- `SEM_DEMO_PRINCIPAL_TENANT_IDS`：生产租户 ID 白名单
- `SEM_DEMO_BINDING_SCHEMA_REVISION=0098_demo_binding_no_truncate`
- `SEM_DEMO_DATABASE_URL`：独立演示库的 `postgresql+asyncpg` 只读账号 URL
- `SEM_DEMO_DATABASE_NAME`：预期的独立数据库名
- `SEM_DEMO_DATABASE_HOST_ALLOWLIST`：精确主机名列表，不支持通配符
- `SEM_DEMO_DATABASE_SERVER_ADDR_ALLOWLIST`：数据库返回的精确服务器地址列表
- `SEM_DEMO_DATABASE_SCHEMA_REVISION`：演示库唯一 Alembic revision

启动只校验配置闭合性，不连接数据库。每次演示读取先从 `sem_prod` 读取可信绑定，然后连接
演示库并设置只读事务。读取前会核验数据库名、服务器地址、事务只读状态、唯一 schema
revision、数据库角色无表或序列写权限、SEM 数据集标记与 binding 的 dataset key/version
一致，以及演示百度账户全部为 `auth_mode=demo`、`sync_status=disabled` 且无 active 账户。

## 发布与数据准备的独立记录

本代码变更没有连接数据库、执行迁移、安装夹具、同步数据、部署或合并。正式启用仍需分别
完成并留痕：生产库部署 0098 binding 契约、创建最小权限演示库只读账号、安装已审核的 SEM
演示数据集及 `dataset_version` 标记、写入生产租户到演示租户的有效 binding、配置精确主机和
地址白名单。任何一项未完成时，受保护演示身份会失败关闭。

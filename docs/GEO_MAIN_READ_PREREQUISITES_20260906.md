# GEO main 只读前置

本批以 `main` 的 `1208157ae09badcc08e22167f7ac49d2218160f0` 为基线，只提供后续旧 GET 改造需要的两个窄依赖，不移植生产分支的整套 `read_routes`、read model 或指标接口。

`app.geo.read_session.geo_read_session` 创建独立 session，并把 `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY` 作为首条 SQL。依赖退出时只 rollback，不 commit；消费代码异常或 PostgreSQL 拒绝意外写入时同样 rollback，然后由 session 上下文关闭连接。

`app.geo.tenant_scope.require_geo_read_entitlement` 直接调用 main 已有的 `app.module_scope.ensure_module_access(session, ctx, tenant_id, "geo")`。因此沿用 main 的租户绑定、`active/trial` 状态和到期日包含当天的规则，没有复制权限逻辑。

与生产 GEO 当前实现的响应差异：生产依赖用 GEO 自己的只读查询，在拒绝时返回 `{code: geo_not_available, message: ...}`；本批按 main 共享逻辑保留现有 HTTP 403 字符串（“尚未开通”或“未启用或已过期”）。可用性判定语义一致，错误 body 暂不强行统一。

验证分为不依赖数据库的 session 生命周期、异常清理和 entitlement 参数化测试，以及设置 `GEO_TEST_POSTGRES_URL` 后运行的专用 PostgreSQL 测试。PG 测试只接受 loopback、`geo_ci` 用户与 `geo_ci` 数据库，验证隔离级别、只读写阻断、rollback 和连接归还。

# GEO 项目客户只读接口

`/api/v1/geo/projects/{project_id}/client` 提供 overview、visibility、questions、
answers、content、variants、articles、deliveries 共 12 个 GET 路由。
响应使用 `geo.client.v1` 外壳；所有请求必须携带 tenant_id。

每次请求验证现有登录身份、assets/content 两项权限、客户绑定、实时模块、
active 项目、顾问分配及当前业务→单元→问题归属。详情经同一合法引用链读取。
空业务绑定返回空项目；无效归属拒绝读取。演示数据源返回 403。

正式指标沿用现有巡检证据和周计算函数，按上海时区已结束完整周，
须满足 8 回答、3 问题、2 引擎。缺样本返回 null 和 insufficient；合格真零保留 0。
项目自有域仅取项目 canonical_domain 与本客户启用 website/docs 渠道的交集。
单题只显示真实可判读观测 X/Y。客户确认、原生发布登记、原生回执和已存页面核验分别投影。

分页游标使用既有运行时签名配置，绑定客户、项目、父任务、周期、全部筛选、
归属链指纹和首屏水位。归属变化返回 409；篡改或换范围返回 400。
水位防止后续新增 ID 混入，不提供跨请求的数据库历史快照。

查询开启 PostgreSQL READ ONLY / REPEATABLE READ，并禁用 autoflush，退出总是 rollback。
单条 SQL 超时 5 秒；每类记录、巡检 cell 总量及回执总量上限各为 10000。
超限或查询失败返回安全 503，不返回静默截断的汇总。响应不缓存。
未增加迁移、表、环境开关或部署配置。未调用旧 GET 的初始化、恢复、采样、生成、发布、抓取或重试能力。

本地离线验证：

```powershell
py ops/run_geo_client_checks.py
```

此命令构造合成设置，不读取 dotenv，阻断 PostgreSQL 与普通外部连接入口。
新 HTTP 测试仅用 SQLite 内存表，拦截非 SELECT，逐路由比较持久化内容，
验证租户/项目/父对象隔离、顾问分配、模块撤销、缺数、证据、周边界、分页和字段裁剪。
模型中的 captured_at 非空；测试复制的内存 DDL 单独允许 null 来覆盖契约的防御性缺时间路径。
已有 PostgreSQL 专属回归在没有隔离测试库时仍会跳过；未连接或验证生产数据。

前端 PR 独立基于 codex/production-sem，并按同一 CONTRACT.md 构造请求。
后端 PR 基于 codex/production-geo；两者无需相互合并，也不依赖 SEO 草稿 #768。

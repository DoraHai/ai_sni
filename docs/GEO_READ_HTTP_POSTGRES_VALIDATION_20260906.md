# GEO 隔离 HTTP / PostgreSQL 验证

代码基准611d331；新增 tests/test_geo_read_http_postgres.py，仅测试变更，不含运行时代码或生产迁移。2026-09-06 在本机独立 PostgreSQL 16.15 实例完成测试，未连接生产或复用 SEM/SEO 数据目录。

## 结果

- 新增两组集成测试：2 passed，无跳过。
- 全量 `python ops/run_geo_checks.py --postgres`：949 passed、1 skipped、1 warning；唯一跳过为 test_geo_followup_scheduler.py 的 Linux flock 测试（Windows平台）。这不是数据库测试跳过。
- 未改变前端，本轮不重复构建。611d331部署时前端143通过的记录仍是前轮结果。
- 本轮采用本机临时实例，不再推测试分支或触发CI重复验证，也不推production-geo或部署。精确冻结测试提交见本次Git记录；生产仍611d331。

## 真实覆盖与身份边界

1. 真实 FastAPI HTTP 依赖链 + 原生 tenant_modules SQL：active、trial、到期日当天、过期、过期trial、disabled、cancelled、仅SEM、未开通共9种数据，逐一检查9个read入口及2个指标入口（99次请求）。允许客户对不存在实体返回404；拒绝客户应先403，不能借404绕开资格判断。配置表在隔离schema临时缺失返回500，不能放行；撤销已通过客户的资格后下次请求立即403。
2. fixture仅覆盖require_auth以提供合成AuthContext；保留实际require_scoped_auth及require_geo_read_entitlement。无菜单、跨绑定客户403，同客户view正常。没有签发或解析真实JWT，没有读取生产User/Role，没有验证登录撤权数据库链，不能称真实身份联调通过。
3. 非空回答通过真实HTTP/SQL读取，覆盖同时间按ID倒序、4页无重无漏、并发新插入的水位隔离、跨客户及错客户问题关联不泄漏、游标绑定客户/引擎/页大小/来源、原文详情、来源过滤、上海半开周边界、明确UTC/+08时间。
4. 历史巡检问题/模型/供应商优先于当前编辑的问题/当前引擎模型；7条合格回答仍为整周不足，区别模拟/人工/未知单条排除与窗口外排除。NULL时间只是兼容性夹具，复制表放宽了nullable，不代表正式schema允许写入NULL。
5. 所有请求数据库会话使用 READ ONLY / REPEATABLE READ。合成数据装载、资格撤销、分页期间插入和临时移除表只通过独立fixture写连接，不由HTTP查询执行。既有test_geo_read_postgres实际拒写测试也已在全量中执行。

## 隔离与清理

复用公开PostgreSQL二进制，仅对GEO独立ASCII临时目录初始化实例，监听回环地址的临时端口。测试连接入口只接受专用回环geo_ci数据库/角色；不读取生产.env或连接凭据。每组测试创建随机geo_read_http_* schema，仅复制所需列类型和合成记录，finally删除自己的表与schema；不执行应用启动、Alembic、采集或生成。

临时实例已停止；临时目录保留合成数据和运行日志以便检查，没有客户资料。未修改原二进制或SEM/SEO实例配置。本轮不需要数据库人员协助。

仍待：权威身份/角色环境中的真实JWT联调；旧GET运行时拆分需负责人审查方案后协调，不由这些测试暗示已修复。

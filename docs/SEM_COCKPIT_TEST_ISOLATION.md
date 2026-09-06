# A/B 最小读取包的测试隔离

开发基线main6296a130b0efe0e4130779f6c6d99594c481ef26。仅测试组织与本文变化，无运行时、workflow、依赖或schema变更。

## 文件和保留范围

- tests/sem_cockpit_fixtures.py：独立的假配置、ReadSession、SQLite连接/仅SELECT检查、A报告种子、B六表合成模型/种子；不再从测试模块导入公共工具。
- tests/test_sem_cockpit_readonly.py：仅A报告与参数/权限拒绝测试，不注册leads路由、不建Lead表。
- tests/test_sem_cockpit_leads.py：完整保留原线索统计、分页筛选、个人数据排除、缺失金额与权限拒绝用例；使用独立Lead数据，不依赖报表表或新A接口。
- tests/test_sem_cockpit_details.py：全部原B测试主体保留，共享工具改为从fixture模块导入。
- tests/test_sem_cockpit_postgres.py：原生矩阵主体不变，直接导入共享fixture，不导入B测试模块。

原13个测试函数的断言主体逐一AST比对保留；原同时参数化dashboard/leads的3个函数分到两文件各保留一路，合计16个函数但参数化用例总数不变。没有删测试、增加skip或依靠-k排除失败。完整开发集合仍132项SQLite/mock；最小包排除的是独立线索发布范围，对应12项线索测试在开发分支全部保留并通过。

## 最小候选及本次实测

独立本地候选以生产5af9d3d8da83efac8c90dc8853d99523f3d7f193为基线，仅5个app文件取自已审main6296a13：api/dashboard.py、api/keywords.py、api/search_terms.py、sem_cockpit_readonly.py、sem_cockpit_details.py。
测试侧仅加入上述fixture、A、B、PG四文件；leads.py、models、auth、module_scope、requirements、migrations不变，不同步main其他源码，也不向实际生产分支推送。

本次真实运行结果：

| 环境/集合 | 结果 |
| --- | --- |
| 开发分支：A、线索、B、tenant identity、identity preview、mock keyword refresh | 132 passed，无skip |
| 开发分支：原生PostgreSQL矩阵单独运行 | 1 passed，无skip |
| 五运行时文件候选：A、B、原生PG、tenant identity、identity preview、mock keyword refresh | 121 passed = 120 SQLite/mock + 1原生PG，无skip |
| 已审消费客户端 | Node 11 passed，无skip |

仅既有jieba/pkg_resources弃用警告。没有运行真实同步/刷新；keyword refresh为既有mock测试。
原生PG16.15实际在专用127.0.0.1:55483、sem_cockpit_ro_test/sem_cockpit_fixture环境执行，独立UUID schema夹具，验证JSONB类型、Decimal聚合、READ ONLY事务及拒绝UPDATE的SQLSTATE25006，结束清理自己的schema。验证完成后pg_ctl stop，status确认no server running；不连接生产数据库，不执行应用startup/Alembic。

## 非部署验证命令

先在隔离进程显式设置dummy应用配置，避免继承开发者真实DATABASE_URL、API Key或百度配置。沿用fixture的假值即可，不打印实际凭据。
最小候选SQLite/mock验证（不包含PG文件，因此不会把缺PG配置skip记成成功）：

```text
python -m pytest -q tests/test_sem_cockpit_readonly.py tests/test_sem_cockpit_details.py tests/test_sem_tenant_account_identity.py tests/test_sem_identity_repair_preview.py tests/test_keyword_refresh.py
```

开发分支另加tests/test_sem_cockpit_leads.py，保证线索完整回归。PG须独立启动已批准的本地/CI合成实例，设置SEM_COCKPIT_TEST_DATABASE_URL，先检查变量非空再执行：

```powershell
if (-not $env:SEM_COCKPIT_TEST_DATABASE_URL) { throw 'PG证据未配置，不能算原生验证通过' }
python -m pytest -q tests/test_sem_cockpit_postgres.py
```

PG测试自带专用loopback、driver、用户名、库名、非5432端口检查；不能用生产URL绕过。没有配置时原测试仍skip，报告必须写“未执行”；要获得发布门禁通过必须有实际1 passed证据。
消费适配在含integrations交付目录的已审源码运行：

```text
node --test integrations/sem-cockpit/readonly-client.test.mjs
git diff --check
```

运行前后核对最小候选app差异仅五文件，其他已有生产app文件无变化。测试辅助文件不随当前后端archive进入运行时；归档只取app、migrations、requirements.txt、alembic.ini。

## workflow最小方案（只提案，未改）

现有后端dispatch固定测试集合需后续独立审核加入A与B专项路径；共同fixture自动导入即可。PG采用显式隔离实例/必填变量的单独检查，不用当前可选skip作为发布门禁；Node消费契约单独运行并关联源码SHA。
先在非部署PR CI验证最终候选；如后续调整workflow，必须说明它在main执行但checkout生产候选SHA，确认所有测试路径存在。不要新增自动生产触发，不调用apply、不修改已有确认串或production environment门禁。仅后续获得明确授权后才改workflow。
开发main全量测试继续收集线索文件；最小候选没有线索文件是范围分离，不是给已包含但失败的用例设置skip。

## 仍未验收

HTTP fixture覆写JWT上下文并mock模块资格与SEM身份guard，只验证调用及拒绝传播；真实JWT、实际module资格和身份联调未完成。隔离PG合成表不证明生产schema、读权限或RLS兼容，CI SemTask PG也不替代本矩阵。
后端部署重启会启动既有scheduler；请求只读不等于整个重启期间不存在既有调度。服务器证据复用既有current/完整旧产物/受控回滚结果，数据库只需schema/SELECT/RLS只读结论，无迁移申请。

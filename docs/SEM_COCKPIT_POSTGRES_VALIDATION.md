# SEM B 包隔离 PostgreSQL 验证条件

状态更新：已完成本机独立PostgreSQL **16.15实例**测试（不是仅SQL编译）。
A已合main不等于已部署，B仍为本地未提交代码。未使用SEO实例、生产库或客户数据。
初次原生测试发现SUM(bigint)返回Decimal引起CPC类型异常，已将计数显式转int修复并重测。

触发条件：PostgreSQL对BigInteger点击/展现求SUM时返回numeric，asyncpg交付Decimal；
原实现执行float(cost)/Decimal(click)抛TypeError，读取会失败。修复将整数计数聚合显式转int，
不截断金额。返回click/impression为JSON整数；cost为CNY浮点数保留2位、CPC为CNY/click浮点数保留2位，
CTR为ratio浮点数保留6位；零分母为null。金额先用数据库Numeric/Decimal求和再转换显示值，
响应浮点数不是任意精度金额计算接口。
原生夹具10.01元/3点击/7展现实测返回cost=10.01、cpc=3.34、ctr=0.428571，计数为int。
SQLite/既有mock测试132项，原生PostgreSQL集成矩阵1项，Node消费11项，全部通过、无跳过。
写入拒绝证据位于tests/test_sem_cockpit_postgres.py中`SET TRANSACTION READ ONLY`及
`sqlstate == "25006"`断言：只对新建合成schema尝试UPDATE，数据库拒绝后rollback。

## 环境与权限

本轮自行复用本机已有公开PostgreSQL二进制，在独立ASCII路径初始化**专用、可丢弃的测试实例**。
中文二进制路径首次初始化失败，复制运行时到ASCII路径后成功，未改动原运行时或SEO数据目录。
禁止复用任何生产库、只读副本或客户数据。
库名建议`sem_cockpit_ro_test`，与应用DATABASE_URL严格分离。连接信息通过受控渠道交付，
不写在本文、Git、测试输出或聊天交接中。

复测可分两个角色：fixture角色仅在专用库创建合成测试表/装载夹具；reader角色只具备
CONNECT、schema USAGE及这些表的SELECT。reader不得拥有写入、建表或修改schema权限。
本轮使用专用fixture角色，所有业务读取放在transaction_read_only=on事务内；
显式测试UPDATE得到PostgreSQL SQLSTATE 25006拒绝，随后rollback。没有成功执行业务写操作。
测试只需baidu_accounts、keywords、kw_report_snapshots、keyword_region_reports、
keyword_hourly_reports、search_term_reports六张合成表；不运行应用启动、不创建SemTask、
不调用Alembic，也不复制生产全库或生产账户Token。

网络限制：验证进程允许连接该测试PostgreSQL；百度API和AI调用继续使用失败桩，
禁止外部同步、补采集或业务写入。固定夹具在读取阶段开始前装载。

## 由SEM负责人执行的具体用例

复用`tests/test_sem_cockpit_details.py`内合成夹具的账户/关键词/窗口/权限场景，
已抽取可复用夹具，并新增`tests/test_sem_cockpit_postgres.py`：表使用原生PostgreSQL类型（尤其JSONB），
asyncpg真实执行SELECT；每次新建随机测试schema，结束仅清理该schema，不运行迁移。
桥接仅接受SEM_COCKPIT_TEST_DATABASE_URL，要求127.0.0.1、非5432端口、
专用库名sem_cockpit_ro_test、专用角色sem_cockpit_fixture，其他目标拒绝；未配置时明确skip。
本次实际配置后执行通过，不将skip计为通过。连接信息不输出到日志。

执行命令（环境变量由本地测试启动器提供，不复制生产配置）：

```text
python -m pytest -q tests/test_sem_cockpit_postgres.py
```

| 用例 | 数据安排 | 必须得到的结果 |
| --- | --- | --- |
| JSONB类型及数值 | 电话点击字段为0、2、"2.0"、缺失、null、true/false、数组、对象、负数、小数、NaN文本 | 仅明确非负整数计入；部分覆盖value=null，known_subtotal保留；布尔不变成0/1 |
| SQL分组绑定 | 多账户、多种JSONB值重复出现 | jsonb_typeof/字段提取GROUP BY实际执行无绑定或类型错误；计数与SQLite结果一致 |
| 账户隔离 | 同租户账户11、12，外租户21，NULL归属报告 | 指定账户不串数，外租户404/403；NULL不推到已知账户 |
| 日期/缺报 | 09-01有值、09-02无行、09-03有零行 | 缺报null，有记录零值为0；起止包含，过长/不完整日期拒绝 |
| 独立维度鲜度 | 日报、地域、小时各用不同fetched_at | 各自返回更新时间；省市分层，无重复总计；星期×小时缺格null |
| 搜索词窗口 | 账户11九月窗口，12八月窗口，分页1条 | windows覆盖全部筛选结果；mixed_windows=true，无跨窗口汇总 |
| A/B边界 | A请求、B详情分别执行 | A不查询电话点击字段；B只按原始字段覆盖输出 |
| 只读与权限 | reader运行、无菜单/跨客户/模块禁用/身份拒绝 | 不出现DML；拒绝请求不泄漏数据，不触发百度/AI/缓存 |

记录PostgreSQL版本、代码SHA/未提交补丁摘要、用例通过数、查询错误（脱敏）、只读角色结果。
查询计划仅对合成数据做EXPLAIN，不以小夹具耗时承诺生产性能。不能把SQL编译通过记为实例执行通过。

## 后续真人联调（不是本地测试的阻碍）

实际服务联调需要普通SEM只读用户及无optimize.keywords/optimize.searchterms权限的用户，
以及已授权测试租户。相关需求统一报工作台负责人汇总，不再分别向用户索要；凭据通过受控渠道交付。
服务器负责人提供联调地址、真实部署SHA与发布记录；未收到前不声明可联调。

SEM负责人负责提供/执行多账户、缺报、零值、字段覆盖及API拒绝脚本；
工作台「开发1.0」负责人负责页面、对话、客户切换与跨模块联合验收；
用户负责协调真人及环境，不需要自行设计测试用例。

确切当前阻碍：实际联调部署版本、测试身份与租户授权未确认。隔离PG环境请求已自行解决，
不再需要用户协调数据库人员建立测试库。后续确需数据库人员参与时，先报工作台负责人汇总。
当前无必须客户本人判断或操作的测试项目，故“待真人测试”为无；API/浏览器可自行验证的部分
在联调前置就绪后由开发者执行，不把环境等待改称真人验收。
生产部署由工作台负责人按新增授权协调；迁移、采集及真实业务写入不在授权内。

# SEO 独立演示运行环境与空库迁移审计

本审计落实跨模块协调决定 `1f46fab9`：SEO 演示夹具不进入生产业务库，后续只允许独立 demo runtime 连接独立 demo PostgreSQL。当前分支继续保持未合并、未部署；本轮没有连接或创建数据库，也没有实现 apply。

## 空 PostgreSQL 执行现有迁移

当前分支共有 111 个历史迁移文件，Alembic 图只有一个 head：`0094_seo_qa_batches`，其末端链路为 `0092_seo_cockpit → 0093_seo_qa → 0094_seo_qa_batches`。SEO `/health/seo` 接受 `0094_seo_qa_batches` 和经过审核但尚未进入正式迁移目录的 `0095_sem_tasks`。因此使用本仓库正式迁移创建空演示库时，预期终点是 `0094`；不能 stamp 到 `0095`，也不能把候选 SQL 当成正式迁移。

`alembic upgrade head` 不是 SEO-only 建表过程。迁移从 `0001` 开始，依次创建共享 SEM、认证、GEO 和 SEO 对象。空库至少要求：

- PostgreSQL 数据库及专用 owner/migrator，能够创建和修改 table、sequence、index、foreign key、check/unique constraint；迁移未声明额外 extension。
- `public` schema 可用。当前模型和迁移没有 demo 专用 schema 参数，所有共享表都写入默认 schema。
- 迁移运行时仍需提供 Settings 的必填占位配置，但外部服务凭据不得使用真实值。`migrations/env.py` 会导入全部模型并读取 `DATABASE_URL`。
- 共享基础表包括 `tenants`、`users`、`roles`、`tenant_modules`。SEO 夹具还依赖正式 SEO 表、序列和外键；普通演示登录身份需要认证负责人另外创建普通 user/role 关系，SEO 数据包本身不创建账号。

空库对历史数据迁移是安全的预期：角色权限 UPDATE、OAuth 账户拆租户、旧数据站点回填等语句在空表上应影响 0 行。仍必须在一次性空 PostgreSQL 上真实执行验证，不能仅凭静态审计批准，因为这些历史迁移同时覆盖三个模块并含数据修复逻辑。

离线 SQL 验证目前不能完整生成。实际执行 `alembic upgrade head --sql` 在 `0048_clean_legacy_geo_demo_text` 失败，因为该迁移调用 `op.get_bind().execute(...).mappings()`，offline bind 不返回结果；`0049_geo_demo_statement_cleanup` 使用相同模式。这个失败不证明 online 空库失败，但意味着“离线 SQL 全量预览”目前不是可用验收证据。不能绕过 0048/0049 或手工 stamp。

正式空库演练需要数据库负责人提供一次性、非生产数据库后执行：

1. 开始前核对 `current` 为空、数据库名称和主机命中 demo allowlist。
2. `alembic upgrade head`，确认唯一 revision 为 `0094_seo_qa_batches`。
3. 启动 SEO demo API，但 scheduler 必须从进程级关闭；检查 `/health/seo` 的 db/schema 均为 ok。
4. 执行只读表/列、外键和序列核验，再销毁该一次性数据库。演练日志不得记录数据库密码。

## Scheduler、worker 和外部动作配置

现有配置只有部分开关，不能单靠当前 `.env` 把整个 SEO 服务变成安全 demo runtime。

必须设置为空或 false 的现有配置：

```dotenv
APP_ENV=demo
CHINAZ_API_ENABLED=false
CHINAZ_API_KEY=
CHINAZ_BAIDU_INDEX_API_KEY=
CHINAZ_BAIDU_PC_KEYWORDS_API_KEY=
CHINAZ_BAIDU_MOBILE_KEYWORDS_API_KEY=
CHINAZ_BAIDU_PC_TOP50_API_KEY=
CHINAZ_BAIDU_MOBILE_TOP50_API_KEY=
CHINAZ_BAIDU_PC_RANKING_API_KEY=
CHINAZ_BAIDU_MOBILE_RANKING_API_KEY=
CHINAZ_360_PC_RANKING_API_KEY=
CHINAZ_360_MOBILE_KEYWORDS_API_KEY=
CHINAZ_SOGOU_PC_KEYWORDS_API_KEY=
CHINAZ_SOGOU_MOBILE_KEYWORDS_API_KEY=
SEO_RANK_SCHEDULER_ENABLED=false
SEO_RANK_SCHEDULER_USE_AI=false
SEO_RANK_DROP_TASKS_ENABLED=false
SEO_BACKLINK_INDEX_ENABLED=false
SEO_DATAFORSEO_LOGIN=
SEO_DATAFORSEO_PASSWORD=
SEO_GSC_SERVICE_ACCOUNT_JSON_B64=
PAGESPEED_API_KEY=
DEEPSEEK_API_KEY=
DASHSCOPE_API_KEY=
```

发布平台凭据不来自上述全局配置，而在 `seo_distribution_connections.credentials_encrypted`。loader 必须保证全部连接 disabled、无 credentials；demo runtime 也不能获得生产 `CRYPTO_MASTER_KEY_B64`，避免它解密任何误连数据。

现有缺口：

- `SEO_RANK_SCHEDULER_ENABLED=false` 只让 `collect_daily_seo_rankings` 提前退出。`app/seo_main.py` 仍无条件调用 `start_seo_scheduler()`，其余竞品、问答核验、外链发现/核验、过期抓取修复、快照清理、AI 账务协调、图片核验、驾驶舱指标和 QA 批次 worker 仍会注册并运行。
- 当前没有统一的 `SEO_SCHEDULER_ENABLED=false` 或 `SEO_DEMO_MODE=true` 服务端硬门禁。
- 当前 SEO API/诊断/任务/问答/视频路由合计约 96 个 POST/PUT/PATCH/DELETE 入口，其中仍有入口可启动抓取、生成、账号测试或发布。清空凭据只能使一部分动作失败，不能替代拒绝动作的服务端门禁。
- `Lighthouse` 可在没有 API key 时由本机二进制访问目标页面；只清空 PageSpeed key 不足以禁抓取。

因此 demo runtime 在新增并测试统一门禁之前只能以只读方式暴露：进程不调用 `start_seo_scheduler`，不启动任何额外 worker，网关仅允许经过白名单审核的 GET/HEAD/OPTIONS，且应用层后续还需 `SEO_DEMO_MODE=true` 对所有业务写动作返回 403/409。网关只读限制不能作为最终唯一保护。

本分支随后实现的配置契约：

```dotenv
SEO_DEMO_MODE=true
SEO_SCHEDULER_ENABLED=false
SEO_EXTERNAL_ACTIONS_ENABLED=false
SEO_DEMO_DB_ALLOWED_HOSTNAMES=demo-db.internal
SEO_DEMO_DB_REQUIRED_NAME=gsnipers_demo
```

启动时会 fail closed：`APP_ENV=demo` 要求 demo mode=true、scheduler=false、external-actions=false；配置不完整直接拒绝启动。调度器入口和 lifespan 均再次检查策略，demo 下不获取调度锁、不注册或启动任何 scheduler/worker/startup recovery。HTTP 层允许 GET/HEAD/OPTIONS，以及精确白名单中的认证登录、分发预检、问题导入预览和资料文件预览；其他 POST/PUT/PATCH/DELETE 在路由分发前统一返回 `seo_demo_runtime_read_only`。白名单路径分别为 `/api/v1/auth/login`、`/api/v1/seo/content-distribution/preflight`、`/api/v1/seo/qa/questions/import/preview`、`/api/v1/seo/qa/research/file-preview`。当前 GET 路由静态审计未发现直接调用抓取、搜索平台查询、发布、账号测试或 AI 生成入口。`APP_ENV=demo` 不会触发现有 production secret guard，演示环境仍需独立的强随机 JWT、API key 和加密主密钥，且不得复用生产值。

## Loader 数据库目标门禁草案

`app/seo_demo_fixture.py` 新增了纯校验函数 `validate_demo_database_target`，没有连接数据库，也没有 apply 调用。未来 loader 必须先通过该函数，随后还要在同一连接内用 `current_database()`、`inet_server_addr()` 或平台等价信息二次核对，防止 URL 与实际路由目标不一致。

当前门禁要求：

- `runtime_mode` 精确为 `demo`。
- 只允许 PostgreSQL driver。
- hostname 必须精确命中非空、无通配符 allowlist；不支持后缀匹配。
- database name 必须精确等于独立 demo 库名，并拒绝 `postgres/template0/template1`。
- 返回值不包含用户名、密码或 query，避免日志泄密。

未来 apply 顺序应为：解析 URL并本地拒绝 → 建立连接 → 查询服务端数据库身份并再次拒绝 → 确认空库/批准 revision → 单事务加载 → 安全计数 → commit。任何一步不确定都 rollback；不得提供 `--force`、`--skip-check` 或生产 hostname 例外。

## 本轮结论

迁移图从空 PostgreSQL 建到 `0094` 在结构上可行，但仍缺一次真实空库 online 演练。offline 全量 SQL被 0048/0049 的数据读取迁移阻断。本分支已补统一 scheduler 启动门禁与 HTTP 写动作硬拒绝；尚未实现 loader，也没有启动 demo runtime。数据库回复可以继续并行等待，下一开发门槛是独立审查这组门禁，确认部署拓扑中的 auth 路由和网关只读规则，再进行空库演练。

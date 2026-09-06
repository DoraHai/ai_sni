# GEO questions 生产同步候选与发布清单（2026-09-07）

## 候选边界

- 生产起点必须是 `codex/production-geo@93775504487deb5cdce57d49974bba0a2e01704e`。
- 只新增 `app/geo/question_read_routes.py`，并在 `app/geo/routes.py` 挂载该 router。
- 只增加问题目录单元测试，并扩充生产已有的隔离 PostgreSQL HTTP 测试夹具。
- 不同步 `main` 的共享鉴权改动；生产已经将精确前缀
  `/api/v1/geo/integration/` 映射为 `geo.content`。
- 不包含 #391，不包含前端、迁移、采集、生成、巡检执行或数据库配置改动。

新增接口：

```http
GET /api/v1/geo/integration/read/questions
```

必填参数为 `tenant_id`；可选参数为 `status`、`is_brand_probe`、`unit_id`、
`business_id`、`limit` 和 `before_id`。查询只读取 `geo_prompts`、
`geo_optimization_units` 和 `geo_optimization_businesses`。

## 生产兼容性核对

- 生产的 `GeoPrompt`、`GeoOptimizationUnit` 和 `GeoOptimizationBusiness` 字段与候选查询一致。
- 候选复用生产 `app.geo.read_routes.read_session`，其首条事务语句设置
  `REPEATABLE READ, READ ONLY`；没有引入 `main` 的独立 `read_session.py`。
- 候选复用生产 `require_geo_read_entitlement`：先执行绑定客户隔离，再要求 GEO 为
  `active`/`trial`，到期日为空或不早于当天；查询错误不放行。
- `created_at`、`updated_at` 是历史 `timestamp without time zone`，返回值不添加 offset，
  并显式返回 `timestamp_source_timezone: "unknown"`。`evaluated_at` 单独为 UTC。
- 模块没有导入采集、生成、发布、巡检或配置初始化函数；GET 不触发后台任务。
- 没有模型或迁移变化，不需要执行 Alembic，发布清单必须保持 `migration=not-run`。

## 审查前检查

1. 确认候选差异只包含上述后端模块、router 挂载、测试和本清单。
2. 确认 `origin/codex/production-geo` 仍指向起点 SHA；若已变化，停止并重新核对差异。
3. 跑问题目录、只读模型、开通到期和真实 PostgreSQL HTTP 测试。
4. 跑 `python ops/run_geo_checks.py --postgres`，不得跳过 PostgreSQL 用例。
5. 检查提交没有 `migrations/versions`、前端或共享鉴权差异。

## 受控发布步骤

1. 候选分支只用于 PR 审查，不会触发生产部署。
2. 审查通过后，仅把批准的候选提交合入 `codex/production-geo`。该分支 push 会自动启动
   `production-geo-deploy.yml`；push 本身就是发布动作，执行前必须再次核对生产分支头和批准 SHA。
3. 工作流先运行全部 GEO 回归和隔离 PostgreSQL 并发/只读测试；verify 失败时 deploy 不运行。
4. deploy 构建独立 GEO 前端与后端归档，清单写入准确 commit 和
   `migration=not-run`，只调用 GEO 发布入口。
5. 发布后用普通 `geo.content=view` 测试身份读取 questions：确认 200、租户隔离、分页游标，
   并确认没有新增问题、配置、回答、巡检或异步任务记录。

## 回滚

- 发布前代码回滚基线是 `93775504487deb5cdce57d49974bba0a2e01704e`。
- 发布健康检查失败时，沿用 GEO 发布基线约定的自动恢复上一版。
- 若健康检查通过后发现功能回归，立即回退 questions 候选提交并通过同一 GEO 工作流重新发布；
  因无迁移、无写入和无配置初始化，不需要数据库回滚。
- 回滚后复查既有 `/integration/read/*` 与指标接口，并确认 questions 返回 404。

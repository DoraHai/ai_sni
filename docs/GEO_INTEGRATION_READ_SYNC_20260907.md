# GEO integration/read 回同步边界（2026-09-07）

## 基线

- 已核对生产提交：`93775504487deb5cdce57d49974bba0a2e01704e`
- 本次开发起点：`main@94aba12eb8675ee8f04ae88d04e2e4bbc2c3a16c`

生产提交已经包含以下工作台契约实现：

- `app/geo/integration.py`：正式周指标、指标字典和统一任务契约。
- `app/geo/integration_metrics.py`：完整自然周及正式样本口径。
- `app/geo/read_routes.py`、`app/geo/read_model.py`：回答、周期、能力与任务进度的纯查询读模型。
- `app/geo/content/sample_provenance.py`：真实、人工、模拟和未知来源的判定。
- `app/security/auth.py`：`/api/v1/geo/integration/` 使用 `geo.content` 权限。

上述四个读模型/契约文件及来源判定文件尚未整体进入本开发基线。它们直接依赖生产分支
后续的巡检、异步任务、内容版本和指标实现，连同路由差异超过一千行。因此本次不把生产
目录整树覆盖到 `main`，避免把已分叉的生产实现和无关功能一并倒灌。

## 权限等价同步

本次只同步生产已有的精确前缀规则：

```text
/api/v1/geo/integration/* -> geo.content
```

前缀必须包含 `integration/` 末尾斜杠。`/api/v1/geo/integration` 和
`/api/v1/geo/integration-other` 不命中该规则，继续沿用 GEO 兜底的
`geo.diagnosis` 读取权限。

方法分类继续使用共享鉴权现有规则：

- `GET`、`HEAD`、`OPTIONS` 需要 `geo.content=view|edit`。
- `POST`、`PUT`、`PATCH`、`DELETE` 需要 `geo.content=edit`。

这会改变 `main` 对所有 `/api/v1/geo/integration/` 子路径的权限分类，包括尚未注册的
子路径：它们会先按 `geo.content` 鉴权，然后仍由路由层返回 404。没有放宽任何写方法，
也没有改变 `/geo/audits`、`/geo/prompts` 或其它模块的映射。

## 本次问题目录增量

生产 `9377550` 的回答接口会内嵌已产生回答的问题，但没有独立的完整问题目录。后续独立
提交增加 `GET /api/v1/geo/integration/read/questions`，复用 `main` 已有的：

- `app/geo/read_session.py::geo_read_session`：PostgreSQL `REPEATABLE READ, READ ONLY`，
  结束时只回滚，不提交。
- `app/geo/tenant_scope.py::require_geo_read_entitlement`：认证租户隔离，并通过共享
  `app/module_scope.py` 检查 GEO 为 `active`/`trial` 且未到期。

该增量只读 `geo_prompts`、`geo_optimization_units` 和
`geo_optimization_businesses`，不会初始化配置、创建问题、采集回答或触发生成。

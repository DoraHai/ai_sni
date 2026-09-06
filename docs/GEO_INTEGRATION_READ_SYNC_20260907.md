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

### 请求与分页

```http
GET /api/v1/geo/integration/read/questions?tenant_id=16&limit=50&before_id=120
```

可选过滤参数为 `status`、`is_brand_probe`、`unit_id` 和 `business_id`。结果按问题 ID
倒序，使用 `before_id` 做稳定的游标分页；有下一页时，客户端把
`pagination.next_before_id` 原样传回。`limit` 范围为 1–200，越过最后一页返回空
`items`，不报错也不回绕。

```json
{
  "tenant_id": 16,
  "evaluated_at": "2026-09-07T09:00:00Z",
  "pagination": {
    "limit": 50,
    "has_more": false,
    "next_before_id": null
  },
  "items": [
    {
      "ref": {"module": "geo", "type": "question", "id": 14},
      "current_text": "工业齿轮箱如何选型？",
      "language": "zh-CN",
      "status": "active",
      "question_source": "manual",
      "question_group": "selection",
      "market": "cn",
      "is_brand_probe": false,
      "priority": 10,
      "tags": ["选型"],
      "unit_ref": {
        "module": "geo",
        "type": "optimization_unit",
        "id": 8,
        "name": "工业齿轮箱",
        "status": "active"
      },
      "business_ref": {
        "module": "geo",
        "type": "optimization_business",
        "id": 3,
        "name": "驱动产品",
        "status": "active"
      },
      "created_at": "2026-09-01T01:00:00",
      "updated_at": "2026-09-06T08:00:00",
      "timestamp_source_timezone": "unknown"
    }
  ]
}
```

`question_source` 只说明问题本身如何录入，不是回答的供应商、模型或采集来源。这个接口
没有回答正式准入结论，也不能作为正式指标样本清单。正式指标仍只读取
`/integration/metrics/snapshot`；回答详情必须单独保留真实、人工、模拟、未知来源以及
逐条排除原因。

`geo_prompts.created_at` 和 `updated_at` 的历史数据库类型是 PostgreSQL
`timestamp without time zone`，由数据库 `now()` 或旧写入路径生成，仓库没有能够证明所有
历史值统一采用 UTC 或上海时区的约束。因此接口按实际值返回不带 offset 的 ISO 时间，并以
`timestamp_source_timezone: "unknown"` 明示来源时区未知；消费方不得给它补 `Z`，也不得在
未知来源时区之间做绝对时刻比较。`evaluated_at` 是接口本次查询时刻，单独使用带 offset 的
UTC 时间。

### 隔离与只读保证

- 绑定客户的普通 `geo.content=view` 用户只能读取自己的 `tenant_id`。
- 查询前检查 GEO 模块存在、状态为 `active`/`trial`，且到期日为空或不早于当天。
- 问题、优化单元和优化业务三张表分别带租户约束，异常跨租户关联不会被展开。
- 数据查询使用数据库强制的只读事务；接口代码没有提交、写入、初始化或执行入口。

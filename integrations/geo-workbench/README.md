# GEO 工作台只读 consumer

该 consumer 只读取服务器已经提供的六类 GEO 资源：正式周期、指标快照、指标字典、回答列表、回答详情和问题列表。宿主必须注入普通账号的只读 transport 与已核验的租户、用户、权限版本和完整周；模块不登录、不保存 token、不触发采集、生成、配置初始化或其他写操作。

`authorization-context.mjs` 按生产 GEO 自己的资格边界建立上述上下文。预检顺序为普通账号 `/api/v1/auth/me`、严格的 `geo.content=view|edit`、GEO 自己的 `/api/v1/geo/tenants` 可用租户列表，以及所选租户/完整周的 `period-context` 探针。它不读取 `/auth/modules`，也不把 SEM/SEO 的模块状态当作 GEO 资格；正式 GEO 路由仍在每次请求时执行服务端的 active/trial、到期日和租户门禁。

周期探针返回 `status=insufficient`、零条合格样本或其他缺数原因仍表示请求已通过资格校验，只说明正式周数据不足。它不会被改写成数值零或授权失败。401 表示登录失效；GEO 探针 403 表示所选租户的 GEO 范围不可用；租户不在 `/geo/tenants` 结果中表示当前身份不能选择该租户；网络、服务端和契约错误均保持不可用，不回退到其他模块资格或演示数据。

| 预检结果 | consumer 语义 |
| --- | --- |
| `/auth/me` 401 | `NOT_AUTHENTICATED`，清除上下文 |
| `geo.content` 不是严格 `view/edit` | `NO_GEO_READS`，不请求 GEO 业务接口 |
| `/geo/tenants` 没有所选 ID | `TENANT_NOT_ALLOWED`，不隐式选择首个客户 |
| `period-context` 403 | `GEO_SCOPE_NOT_ALLOWED`，服务端逐请求门禁拒绝 |
| 任一非 2xx（上述状态除外） | `PREFLIGHT_FAILED`，保留 HTTP status |
| JSON、租户、周期或字段不符 | `PREFLIGHT_CONTRACT_MISMATCH` |
| 切租户、周期、权限或退出后的迟到结果 | `STALE_AUTHORIZATION`，不能覆盖新上下文 |
| 周状态不足、合格样本 0、正式指标 `null` | 授权成功；数据状态保持不足/缺数，不生成零值 |

正式指标只来自 `metrics/snapshot`。回答列表用于展示原文、来源和服务器返回的准入/排除原因，不能在浏览器里汇总成正式数。`officialSnapshot()` 复用现有 GEO 展示 formatter，明确保留缺数 `null`、实测零 `0`、不可比较及 `trend_7d=null`。

回答游标是服务器签名的不透明字符串，并绑定首次查询的租户、完整周和全部筛选条件。新的首次查询会撤销旧回答引用；分页只增加当前查询已核验的引用。改筛选、切租户、改权限版本或改完整周会中止请求并清空引用，迟到响应即使忽略取消信号也会被拒收。

分页还记录当前查询中的页边。回答的 `next_cursor` 不得指向当前页或形成多页环，新页不得重复已有回答；同一游标的正常网络重试只有在行 ID 和下一游标都与首次结果一致时才接受。问题页的 `next_before_id` 必须等于本页末条 ID，并严格小于本次 `before_id`。因此重复页不会被误记成新增进展，也不会造成无限翻页。

响应里的 `period_context_url`、`metrics_url`、`dictionary_url` 和 `detail_url` 不能直接导航。consumer 只验证它们是已知的同源相对路径，且 tenant/week 与当前上下文完全一致；实际请求始终从本地路由表重建。问题的 `timestamp_source_timezone="unknown"` 和原时间字符串保持原样，禁止按浏览器时区补写含义。

`production-minimum.synthetic.json` 是根据生产分支 `36b1b23` 的路由及序列化源码整理的六资源最小响应，明确属于合成契约 fixture，不含生产实测数据：

| consumer 资源 | 生产字段出处 |
| --- | --- |
| `periodContext` | `app/geo/read_routes.py:get_period_context` → `app/geo/read_model.py:period_context` |
| `metrics` | `app/geo/integration.py:metrics_snapshot` → `app/geo/integration_metrics.py:build_weekly_snapshot` |
| `dictionary` | `app/geo/integration.py:metrics_dictionary` → `app/geo/integration_metrics.py:metric_dictionary` |
| `answers` | `app/geo/read_routes.py:get_answers` → `app/geo/read_model.py:answer_payload` |
| `answerDetail` | `app/geo/read_routes.py:get_answer` → `app/geo/read_model.py:answer_payload(detail=True)` |
| `questions` | `app/geo/question_read_routes.py:list_questions` → `question_page` |

三个核心 key 由 `weekly_values` 无条件初始化，样本不足时保留 key 并令 `value=null`；`build_weekly_snapshot` 再序列化全部 key。竞品 key 随已跟踪竞品动态增加。周期的 `comparison.comparable/reason_codes` 直接交给现有 formatter：不可比较时即使响应误带 trend 数值也不会显示趋势。

# GEO 工作台只读 consumer

该 consumer 只读取服务器已经提供的六类 GEO 资源：正式周期、指标快照、指标字典、回答列表、回答详情和问题列表。宿主必须注入普通账号的只读 transport 与已核验的租户、用户、权限版本和完整周；模块不登录、不保存 token、不触发采集、生成、配置初始化或其他写操作。

正式指标只来自 `metrics/snapshot`。回答列表用于展示原文、来源和服务器返回的准入/排除原因，不能在浏览器里汇总成正式数。`officialSnapshot()` 复用现有 GEO 展示 formatter，明确保留缺数 `null`、实测零 `0`、不可比较及 `trend_7d=null`。

回答游标是服务器签名的不透明字符串，并绑定首次查询的租户、完整周和全部筛选条件。新的首次查询会撤销旧回答引用；分页只增加当前查询已核验的引用。改筛选、切租户、改权限版本或改完整周会中止请求并清空引用，迟到响应即使忽略取消信号也会被拒收。

响应里的 `period_context_url`、`metrics_url`、`dictionary_url` 和 `detail_url` 不能直接导航。consumer 只验证它们是已知的同源相对路径，且 tenant/week 与当前上下文完全一致；实际请求始终从本地路由表重建。问题的 `timestamp_source_timezone="unknown"` 和原时间字符串保持原样，禁止按浏览器时区补写含义。

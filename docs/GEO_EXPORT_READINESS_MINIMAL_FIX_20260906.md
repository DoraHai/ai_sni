# 旧 export / readiness 最小修复提案（尚未实施）

审查基准611d331。当前仅补测试/方案，未改共享认证、路由实现或190个业务入口。两个GET都满足geo.content view即可通过require_scoped_auth；函数再检查客户绑定/对象归属，但并未额外要求edit，因此存在“查看请求触发写入”。不执行这些生产GET来复现。

## export 调用链、写入与兼容性

GeoTaskEditorView.vue:1908 exportCurrentVariant → geoContent.js:670 exportGeoVariant → GET /api/v1/geo/content-tasks/{task_id}/export → content/routes.py:7776 export_variant。

后端：_get_task客户归属 → session.refresh(task, with_for_update=True) → _variants → 非published渠道稿status=exported；任务ready/editing/needs_fix变exported → _sync_task_pipeline → 缺body_html时渲染并写adapt_meta的body_html/body_plain/has_table/export_format/delivery → variant.export_format=html → commit。

影响字段为任务status/pipeline_step及渠道稿status/export_format/adapt_meta（含时间字段由模型更新）；不是只下载文件。既有published保护和监测历史必须保留。返回quality缺失时当前默认publish_ready，也不应被纯下载视作审核或正式发布资格。

已知调用者除了Vue，还有 frontend/public/deal-sniper-prototype/geo/assets/geo-api-v1.js:424、scripts/smoke_geo_webhook_push.py:298；旧客户端可能把GET后的刷新与exported状态关联。不能仅把后端GET改成POST而不更新调用者。

建议最小包：
1. 将现有状态登记能力迁到同路径POST，沿用当前任务锁、同客户验证、published不降级、监测历史保留及版本校验；POST自然触发现有geo.content edit政策，不改auth.py。模块资格依赖按协调后的范围附加在本模块入口。
2. 保留GET同路径为真正只读内容预览/下载：查询已有渠道稿，需要渲染时仅用内存副本；无行锁、初始化、状态/元数据赋值或commit，返回实际存储状态、质量与审核信息，不把“可复制”描述成“可发布”。对缺失HTML的返回内容保持表格和FAQ格式。
3. Vue及静态台显式导出按钮调用POST后再刷新；仅预览/下载使用GET。同步脚本。旧调用者仍可获得内容，但GET不再登记exported，须在发布说明说明行为变化。客户仍一次审核，不新增人工步骤。
4. 回归：view可GET且记录完全不变、view POST403/edit允许；published不降级、审核不被误授权、监测元数据不丢失；跨客户、旧版本冲突、并发导出/监测及前端迟到响应。真实PG证明GET拒写且POST锁行为符合原约束。

## readiness 调用链、写入与兼容性

geoContent.js:564 fetchOnboardingReadiness → GET /api/v1/geo/onboarding/readiness → content/routes.py:4078 geo_onboarding_readiness → onboarding.py:845 tenant_readiness。

tenant_readiness读取统计/配置后选首个active业务；若存在，则调用onboarding.py:403 attach_orphan_onboarding_facts：选择当前客户active且business_id为NULL的事实，筛选meta.from_onboarding为真，把business_id设为默认业务，随后在953行commit。该写入可能影响事实在各业务中的可见范围，虽未改变事实正文也不应由view请求触发。

已有显式onboarding提交写流程在content/routes.py:4005–4011也调用相同补绑函数，正常新开通路径已有归属处理，不必为修复GET再建新自动后台任务。

建议最小包：
1. 从tenant_readiness去掉补绑及commit，仅报告当前关联缺口；正常onboarding提交继续在其既有写事务处理新事实归属。
2. 不在GET、应用启动或迁移中自动回填历史孤立事实。先输出只读候选数量/原因，若历史确需整理，单列显式、客户范围限定的edit写操作或沿用现有可编辑事实入口，负责人确认后再实施；不强制新增第二次审核。
3. 保留既有readiness响应字段和统计解释；缺关联若需新增提示只做兼容性增量，不声称自动修复。旧页面过去依赖刷新顺带补绑的行为应在发布说明中注明。
4. 回归：存在默认业务+多条孤立事实时GET不改变任何business_id；from_onboarding=False、停用、其他客户和已有business_id均不被改；正常提交写路径仍能正确归属；view GET可读、任何整理动作需edit；用READ ONLY事务实际请求GET确认无commit/UPDATE。

这两项可以作为一个GEO模块内小修复包审查；全局权限政策、共享JWT/模块资格权威服务、其他15个写GET不混入本包。先由工作台负责人协调范围，再实施运行时变更。

# GEO 共用测试租户最小数据约定

这份约定用于 SEM、SEO、GEO 共用的专用测试租户，只验证 GEO 只读菜单、查询契约、租户隔离和模拟样本排除。租户由统筹安排有权限人员统一创建；GEO 不另建租户，不使用真实客户数据，不复制客户配置、渠道凭证或供应商密钥。

## 普通只读账号

- `users.is_active=true`，`users.tenant_id` 必须绑定到专用测试租户，不能留空成为跨租户账号。
- 角色只需要 `permissions={"geo.content":"view"}`。这项权限可显示 GEO 工作台菜单、读取 `module=geo` 的客户列表，并访问本轮 GEO 查询接口。
- 不授予 `geo.content=edit`、`settings.accounts` 或其他模块权限；不用管理员 Key、查询参数 Key 或运维账号代替普通登录态。
- `tenant_modules` 中必须有该租户的 `module_code=geo` 记录，状态为 `active` 或 `trial`，到期日为空或不早于测试当天。其他模块的开通状态由各模块负责人维护。

## GEO 最小合成数据

所有名称和文本以 `[SYNTHETIC][COCKPIT-RO]` 开头，时间使用明确的 Asia/Shanghai 测试窗口并按现有字段要求换算后落库。建议只准备以下对象：

1. 一条 `geo_prompts`：普通问题，`source=manual`、`status=active`，不引用真实品牌、产品或客户事实。
2. 一条 `geo_content_tasks`：关联上述问题，标题带合成前缀，状态使用稳定的 `draft`，不绑定事实、不生成文章和渠道稿。
3. 一条 `geo_async_jobs`：关联上述内容任务，使用终态 `failed`，错误说明为“合成只读验收数据，未执行生成”。不得使用 `pending/running`，避免后台恢复器处理。
4. 一条 `geo_visibility_patrol_runs`：使用终态 `completed`，`trigger=manual`；`summary` 和 `items` 明确写入 `synthetic_test_only=true`，不启动巡检执行器。
5. 两条 `geo_answer_snapshots`：关联上述问题和巡检，一条品牌提及、一条未提及，正文使用 `.invalid` 示例域名。两条都必须同时满足 `sample_mode=mock_persona`、`simulated=true`，`note` 包含 `SYNTHETIC_TEST_ONLY; EXCLUDE_OFFICIAL_METRICS`。

这两条回答只用于核对详情页的来源标签、原文、引用和排除原因。它们不能伪装成 `openai_compat`，不能进入 `/integration/metrics/snapshot` 的正式样本、正式基线或前后比较。正式指标在只有这些数据时应显示“无合格正式样本”的对应结果，而不是把模拟提及算成业务效果。

## 限定表清单

共用租户和账号的创建由统筹方写入以下共享表，GEO 只核对结果：

- `tenants`
- `tenant_modules`
- `roles`
- `users`

GEO 合成夹具仅允许写入：

- `geo_prompts`
- `geo_content_tasks`
- `geo_async_jobs`
- `geo_visibility_patrol_runs`
- `geo_answer_snapshots`

本轮应保持该租户在以下 GEO 表无记录，以验证 GET 返回虚拟默认值且不初始化配置：

- `geo_ai_settings`
- `geo_tracking_engines`
- `geo_publishing_channels`
- `geo_channel_accounts`
- `geo_media_placements`
- `geo_facts`
- `geo_task_facts`
- `geo_article_versions`
- `geo_channel_variants`
- `geo_publications`
- `geo_visibility_patrol_settings`

不向任何凭证列、加密 Key 列或 URL 配置列写值。测试期间不调用采集、生成、发布、再次检查、配置初始化及任何 POST、PUT、PATCH、DELETE 接口。

## 只读验收

- 使用普通账号登录后，GEO 菜单可见，客户选择器只返回绑定的专用测试租户；其他真实租户不可见。
- PR380 的配置类 GET 可返回瞬时默认项，但 `configuration_initialized=false`，上述空表在重复请求后仍为空。
- 内容任务 GET 返回合成任务及空的事实、文章版本、渠道稿和发布记录，不改变任务状态或更新时间。
- PR382 的任务和巡检 GET 返回数据库保存的终态，附带 `status_source=stored`、`reconciliation=background`；重复请求不改变对应行。
- 回答详情必须显示 `simulated/mock_persona` 和排除原因；正式指标不得纳入两条模拟回答。
- 前后核对只比较该租户和给定对象 ID 的行、`xmin` 与摘要。生产后台可能独立恢复其他任务，不能用整表摘要变化认定 GET 写库，也不能暂停后台任务。

## 保留与清理边界

验收结束不自动删除 GEO 合成记录，默认按审计留档要求保留。本轮不装载、不清理任何数据。只有统筹方依据统一审计保留规则明确安排清理后，GEO 才能在指定范围内按外键逆序处理上面五张 GEO 夹具表中的合成前缀记录。共用的用户、角色、模块开通记录和租户始终由统筹方统一处理，GEO 不单独删除或修改。

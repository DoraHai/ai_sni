# GEO 旧配置 GET 纯查询修复（main 移植）

本批以合入 PR383 后的 main `7bfec5521b3173f940f10495ec20be8a4991fa26` 为基线，只移植 PR380 的八个 GET 纯查询行为。复用 main 已有的 `app.geo.read_session.geo_read_session` 和 `app.geo.tenant_scope.require_geo_read_entitlement`，不复制生产分支的 `read_routes`、指标接口、模型、迁移或后台恢复树。

## 修复范围

以下 GET 改用 PostgreSQL `REPEATABLE READ, READ ONLY` 会话，并在原菜单权限之外检查 GEO 开通状态和到期时间：

- `/publishing-channel-options`
- `/publishing-channels`
- `/publishing-channels/auto-push-status`
- `/tracking-engines`
- `/monitoring-stance`
- `/media-placements`
- `/channel-blueprint`
- `/content-tasks/{task_id}`

空配置时继续返回默认渠道、引擎、监测定位和媒体布局，但默认项只在内存中构造，不调用 `add`、`add_all`、`flush` 或 `commit`。返回项增加 `virtual_default`，相关响应增加 `configuration_initialized`，让调用方区分真实配置与展示默认值。既有 POST、PUT、PATCH 写入口继续负责显式创建或更新配置。

任务详情原先通过 `channel_options` 间接初始化发布渠道；现在只合成展示选项。自动推送状态可读取合成渠道，虚拟渠道 ID 为 null、`virtual_default=true`，不会被误报为已配置账号。

## main 前端适配

生产 PR380 修改的旧 `GeoChannelsView.vue` 在 main 已删除，因此本批没有恢复旧页面。对应保护移到 main 当前使用的 `GeoPublishingView.vue`：虚拟渠道可以进入显式“保存渠道”流程，但不能 PATCH、DELETE、切换启用状态或绑定账号；账号选择器只接收已持久化的正整数渠道 ID。

`GeoPlacementsView.vue` 保留 main 的现有结构：虚拟布局可用“加入计划”进入显式创建流程，但不能直接标记发布或删除。通用判断集中在 `geoVirtualDefaults.js`。

## 没有复制的生产依赖

- `app/geo/read_routes.py`：main 不存在，也不需要；由 PR383 的窄 `geo_read_session` 替代。
- 生产专属 `tests/test_geo_legacy_reads_postgres.py`：该文件已从 main 删除，依赖一整套生产旧路由夹具。本批不复活该测试树；路由依赖和虚拟默认由 main 定向测试覆盖，真实 PostgreSQL 的事务只读阻断由 `tests/test_geo_read_session.py` 覆盖。
- PR382 的异步任务、巡检超时观察与后台恢复：不属于 PR380 八个 GET，本批不带入。

本批不创建共享测试租户、不装载合成数据、不运行采集/生成/发布，不改数据库结构、共享认证、SEM/SEO、Nginx 或生产配置，也不部署生产。

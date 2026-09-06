# GEO 旧配置 GET 纯查询修复

基准运行时候选 `2f481ff3afd200f7a4664787dcbd92775d851287`，文档基准 `d400a3544e9a94e3838c6e5ece62115453084302`。本批只改 GEO，不改数据库结构、共享认证、SEM/SEO、Nginx 或生产配置。

## 修复范围

以下 GET 改用 GEO READ ONLY / REPEATABLE READ 会话，并在原菜单权限之外逐请求检查 GEO 开通状态和到期时间：

- `/publishing-channel-options`
- `/publishing-channels`
- `/publishing-channels/auto-push-status`
- `/tracking-engines`
- `/monitoring-stance`
- `/media-placements`
- `/channel-blueprint`
- `/content-tasks/{task_id}`

空配置时仍返回原有默认渠道、引擎、监测定位和媒体布局，但默认项只在内存中构造，不调用 add/add_all/flush/commit。返回项增加 `virtual_default`，相关响应增加 `configuration_initialized`，让调用方区分真实配置与展示默认值。既有 POST/PUT/PATCH 写入口继续负责显式创建或更新配置。

Vue 对虚拟项使用同一判断函数：渠道“保存平台”走 POST，不能删除或绑定账号；账号选择器只接收已持久化的正整数 ID。媒体布局的“加入计划”走 POST，不能 PATCH/DELETE 空 ID。引擎页原本就是整表 PUT，虚拟默认引擎首次保存会由该入口统一创建。监测策略首次保存仍走现有 PUT。

任务详情原先通过 `channel_options` 间接初始化发布渠道；现在只合成展示选项。自动推送状态允许使用只读合成渠道，虚拟渠道 ID 为 null、`virtual_default=true`，不会被误报为已配置账号。

## 验证

- 隔离 PostgreSQL 真实 HTTP/SQL：空配置租户依次读取八个入口，均成功；`geo_publishing_channels`、`geo_tracking_engines`、`geo_ai_settings`、`geo_media_placements` 仍为 0 行；未开通租户返回 403。
- 后端 GEO 全量：957 passed、1 skipped、1 warning。跳过项是 Windows 不支持 Linux 文件锁；所有 PostgreSQL 专项均执行。
- 前端 GEO：159 passed、0 failed；新增定向测试拒绝 null、字符串、负数和伪装成已持久化的虚拟 ID，账号选择器只保留真实行；独立 GEO 构建成功，只有既有大 chunk 提示。
- `compileall` 与 `git diff --check` 通过。隔离 PostgreSQL 已停止。

本批尚未部署。线上 GEO 保持 `2f481ff`，SEM 静态第二阶段仍由负责人按独立条件处理，不因本批代码改变发布基线。

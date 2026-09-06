# GEO 进度 GET 纯查询与后台恢复

基准：生产 GEO `56b1df39622573ffa158e21e224f77f0138242bd`。本批不改数据库结构、SEM、SEO、Nginx、采集、生成或发布。

## 查询契约

以下旧兼容接口改用 GEO READ ONLY / REPEATABLE READ 会话，并逐请求检查 GEO 开通和到期状态：

- `/async-jobs`
- `/async-jobs/{job_id}`
- `/visibility-patrol/runs`
- `/visibility-patrol/runs/{run_id}`

`status` 保持数据库存储值，避免只凭时间把仍由活跃工作进程持有的长任务误报为失败。响应同时返回：

- `stored_status`：数据库状态；
- `stale`：按 pending/running 阈值计算的疑似超时事实；
- `stale_reason=elapsed_threshold_exceeded`：达到时间阈值；
- `status_source=stored`：状态未由 GET 推导或改写；
- `reconciliation=background`：最终持久化由后台恢复负责。

GET 不获取任务执行锁，不调用 reconcile，不 commit，也不释放内容任务状态。

## 后台持久化恢复

- GEO 服务启动时继续恢复异步作业，并新增孤立 `generating/adapting` 内容任务释放。
- GEO 服务启动时恢复巡检：无活跃执行锁的中断 running 记失败；未超时 pending 重新排队，超时 pending 记失败。
- GEO 独立调度器每分钟执行一次异步作业、孤立内容任务和巡检恢复。
- 异步作业与巡检分别使用 PostgreSQL advisory lock。活跃执行者持锁时，后台恢复跳过该任务；进程退出后数据库自动释放锁。
- 手动异步巡检、同步巡检以及两套现存 GEO 调度入口都通过巡检执行锁，避免重复执行和超时误杀。

## 验证

- 定向单元测试：41 passed、1 Windows 平台锁测试 skipped。
- 隔离 PostgreSQL HTTP/SQL：四个旧 GET 返回 stored running + stale，读取后数据库仍为 running/generating；后台 tick 后异步作业和巡检为 failed、内容任务为 editing。
- GEO 全量隔离 PostgreSQL：968 passed、1 skipped、1 warning；跳过项仅为 Windows 不支持 Linux flock。
- `compileall` 与 `git diff --check` 通过。

## main 同步边界

当前 `origin/main` 与 `codex/production-geo` 从共同基点后分别有大量提交，生产侧 GEO 差异涉及 109 个相关文件。只把本批或 PR 380 的末端提交 cherry-pick 到 main 会缺失模型、路由、前端和测试依赖，不能作为安全同步方案。应单独建立 GEO subtree 同步 PR，以生产 GEO 为来源、main 为目标，冻结精确生产 SHA 后审查完整路径差异并跑 GEO 全量门禁；在该 PR 完成前，任何 main 发布流程都不得覆盖 `/opt/geo-service` 或 `/opt/geo-frontend`。

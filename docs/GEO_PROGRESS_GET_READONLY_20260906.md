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

前端看到 `stale=true` 且存储状态仍为 pending/running 时显示“疑似超时，等待后台恢复确认”，不会把时间判断冒充最终失败。母稿异步轮询每 2 秒检查、页面跟随最多 12 分钟；新协议任务通常由一分钟恢复循环先持久化终态。巡检启动页最多轮询约 60 秒后刷新，历史区继续展示疑似超时。后台不可用时状态仍保持数据库原值，界面不会显示已失败或已完成。

## 后台持久化恢复

- GEO 服务启动时继续恢复异步作业，并新增孤立 `generating/adapting` 内容任务释放。
- 异步内容作业的启动重排是生产基线已有行为，本批没有新增这类采集/生成启动入口；新增锁用于阻止多个 worker 重复接管。
- 巡检启动恢复是本批新增的状态修复，但不会重排或启动 pending 巡检：未超时 pending 原样保留，超时 pending 只记失败；带 `advisory_v1` 执行协议且无活跃执行锁的中断 running 记失败。
- GEO 独立进程的监督循环每分钟执行一次异步作业、孤立内容任务和巡检恢复；即使共享旧进程持有巡检调度器文件锁，恢复循环仍会运行。
- 异步作业与巡检分别使用 PostgreSQL advisory lock。活跃执行者持锁时，后台恢复跳过该任务；进程退出后数据库自动释放锁。
- 手动异步巡检、同步巡检以及两套现存 GEO 调度入口都通过巡检执行锁；只有持锁包装器会把执行标记为 `advisory_v1`，执行本体被直接调用时不会伪造协议归属。
- 共享旧进程可能仍在执行未持新锁的巡检。此类 running 行没有 `advisory_v1` 标记，只报告 stale，不自动失败；待旧执行窗口结束后再受控处理，避免新旧版本共存时误杀。
- 恢复在取得 advisory lock 后用 `SELECT ... FOR UPDATE` 重新读取状态和协议，再决定是否写失败；即使外层先读到 pending、旧 worker 随后提交未标记 running，也会在锁内重新识别并保留。

## 验证

- 竞态修复后的定向后端与 PostgreSQL 测试：31 passed；包含两个真实数据库会话的 pending → legacy running 交错。
- 隔离 PostgreSQL HTTP/SQL：四个旧 GET 返回 stored running + stale，读取后数据库仍为 running/generating；后台 tick 后异步作业和巡检为 failed、内容任务为 editing。
- GEO 全量隔离 PostgreSQL：971 passed、1 skipped、1 warning；跳过项仅为 Windows 不支持 Linux flock。
- 前端：166 passed、0 failed；生产构建成功，只有既有依赖注释与大 chunk 提示。
- `compileall` 与 `git diff --check` 通过。

## main 同步边界

以共同基点 `cdfee3337f8838672b9dd6b2bb998c38b010f300`、`origin/main` 与生产基线 `56b1df39622573ffa158e21e224f77f0138242bd` 复核，生产侧共有 250 个严格 GEO 相关文件发生过变化：82 个文件 main 也修改过，168 个仅生产侧修改。后 168 个中，94 个属于运行时代码、迁移或运维入口，74 个属于后端/前端测试；94 个只能作为“生产侧独有运行文件”的盘点下限，不能脱离那 82 个双边修改文件直接同步。只把本批或 PR 380 的末端提交 cherry-pick 到 main 会缺失模型、路由、前端和测试依赖，也不能作为安全同步方案。应单独建立 GEO 同步 PR，以生产 GEO 为来源、main 为目标，冻结精确生产 SHA 后逐文件处理双边差异并跑 GEO 全量门禁；不能整棵覆盖，也不能改动 SEM、SEO、共享认证或部署配置。在该 PR 完成前，任何 main 发布流程都不得覆盖 `/opt/geo-service` 或 `/opt/geo-frontend`。

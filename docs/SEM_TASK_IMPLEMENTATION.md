# SEM 任务基础设施（2026-09-06）

## 当前交付边界

开发基线 main `2194ead5aacb8e8c610c8ab5f79d498a9ff538e4`。
实现模型、CRUD、服务器指标验收、测试；尚未上线、未建设前端任务页面、未对接驾驶舱。
`SEM_TASKS_ENABLED=false` 默认拒绝所有任务请求（503），不查询任务表，不自动建表。
普通 SEM 后端发布继续 `migration=not-run`，不得因合并这些代码就打开配置。
没有修改审批/真实回写逻辑，也不提供任何执行广告操作的任务类型。

## 接口与权限

全部路径为 `/api/v1/sem/tasks`，必须提供正整数 query `tenant_id`。
请求体不得传入租户、创建人、基线、完成证据或 module 来替换服务端归属。
查看同时要求 `monitor.dashboard` 与 `verify.adjustments` 查看权限、客户范围和 SEM 模块有效。
写入另要求 `verify.adjustments` 编辑权限和真实登录用户 ID，API Key 超管不能代替实名创建人。
角色 operator/admin 仅表示任务分工，不授予额外权限；created_by 固定服务端 `user:<id>`，cockpit 不开放。

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| POST | 空后缀 | 创建并保存服务端观测基线；目标须与基线有严格差异 |
| GET | 空后缀 | status/action_type 筛选，id 倒序游标 before_id，limit 1–100 |
| GET | /{id} | 客户限定详情，不存在/其他客户记录返回 404 |
| PATCH | /{id} | 只改 title、assignee_role、open/in_progress/cancelled；不可改目标或证据 |
| DELETE | /{id} | 软取消；不删除审计记录；重复取消幂等 |
| POST | /{id}/verify | 从指标接口重新取本地数据并校验，不调用百度，不自动刷新 token 或补报 |

done/cancelled 为终态。done 只能由 verify 产生，重复 verify 返回原证据，不改时间。
客户身份修复预演明确将 sem_tasks 列入 excluded_scope，并要求独立任务证据归属审核；
不把它当作可直接重新分配 tenant_id 的业务表，不在未建表环境查询该表。
写操作锁定客户范围内的任务行，避免并发取消和完成覆盖。数据库错误由请求会话关闭回滚。
列表以不可变 id 游标分页；不要将 id 连续性或列表大小当作业务成功率。

创建示例（任务不是广告操作指令）：

```json
{"title":"处理待审批记录","action_type":"metric_target","assignee_role":"operator",
 "params":{"metric_key":"sem.approvals.pending_count","direction":"down","target_value":0}}
```

## 首版证据口径

只支持 `metric_target`：active_count 上升、pending_count 下降、conflict_tenant_count 从 1 到 0。
这三个指标的精确定义继承 SEM_FOUNDATION_CONTRACTS.md；账户数仅本地 active，待审批数下降
不代表广告执行成功或效果提升，身份冲突数仅当前客户的 0/1，不是全站数。
暂不支持月花费/预算比例目标，因为跨月、补报与预算变更可能使基线不可比。

创建时持久化客户范围、来源契约版本、metric_key/value/unit/as_of/definition/data_status 及观测时间。
完成时要求指标 available、有值、最新时间不超 5 分钟且不在未来、晚于基线，同客户/范围/来源/
key/unit，严格产生目标方向变化并达到阈值。冲突客户仅允许使用冲突指标，不读取其余不可用指标。
基线及结果以 JSON 嵌入任务记录，来源指向 `sem.metrics.snapshot.v1`，不是未来会变化的 URL。
证据不是不可篡改的外部账单，也不证明任务与指标变化的因果关系；数据库管理员仍能改库。
目标/基线创建后不可修改，取消后重建新目标。没有人工 done、自传证据或任意 URL/SQL/动作执行。

## Schema 单独审核（不是已实施迁移）

候选 DDL：`SEM_TASK_SCHEMA_REVIEW.sql`，仅审核稿，未进入 migrations/versions。
新增一张 `sem_tasks`：共享任务字段及额外 baseline_snapshot（保存不可由客户端覆写的创建时观测）。
tenant_id 为 INTEGER，与当前仓库 tenants.id 类型一致；id 为 BIGSERIAL。
两个索引 `(tenant_id,status,id)`、`(tenant_id,action_type,id)` 与 API 的 id 游标一致，
不同于初稿的 created_at 排序；无需 JSON GIN 索引。不改变任何旧表、不回填生产数据。
外键 RESTRICT；状态、模块、动作、角色、JSON 对象及完成证据非空由数据库约束辅助。
证据真实性及目标达成不能仅由 CHECK 保证，由服务层负责。

静态 AST（包含带类型注解的 revision/down_revision）检查现有唯一迁移头为
`0088_seo_image_alt_reviews`。没有执行 Alembic 命令或加载生产数据库。
当前 SEO 健康检查/迁移测试绑定该头；SEM 后端生产分支与 main 的迁移历史也不应直接视为相同。
因此不能盲目以该头追加 SEM 迁移，更不能随 SEM 发布补跑整个 main 的待执行 SEO 迁移。
正式迁移的 down_revision 尚未确定：需要独立授权后只读核对实际生产 revision、表类型/存在性、
数据库归属和各分支迁移图，再确定独立受控迁移方案；不能修改历史迁移来绕开。

部署顺序：Schema 审核 → 独立受控建表方案审核与执行 → 确认表/索引/权限 →
独立后端同步 PR 与发布 → 经授权启用配置。普通部署绝不执行 DDL 或 Alembic。
建表外键可能短暂锁住 tenants，需独立维护窗口与锁等待限制；若目标表已存在应停止核对，
不使用 IF NOT EXISTS 掩盖结构差异。DDL 不含删除/回填，不提供破坏性降级脚本。
回滚：关闭任务配置、回退应用；保留 sem_tasks 及审计数据，禁止删表清空客户任务。

## 验证

接口单测覆盖越权、伪造字段、权限撤销、未授权模块、关闭功能、无效 ID、缺失/过期指标、
目标未达成、终态保护、软取消、稳定分页、幂等验收；原生 PostgreSQL 覆盖并发锁、
真实约束、外键 RESTRICT 和带时区时间。
CI `sem-task-contracts` 使用一次性 postgres:16、固定虚拟凭据，无生产 Secret。
本地测试仅允许专用 `sem_tasks_test` 数据库和 localhost，随机 Schema 只清理自己的数据。
不运行任何迁移；这不替代生产 Schema 兼容性验收。

本轮实际结果：扩大 SEM 回归 846 passed；集成回归 1816 passed（未收集
test_seo_migration_merge.py，以及 foundation/writeback_health/postrelease 三组其他
PostgreSQL 文件）；随后新增 OpenAPI 契约测试，任务专项 46 passed，包含本功能原生数据库测试。
既有 jieba/pkg_resources 弃用警告 1 条，无新增失败。`git diff --check` 通过。
本地新建专用 PostgreSQL 集群绑定 127.0.0.1:55449，数据库 sem_tasks_test；测试结束停止该实例。
没有启动或停止任何生产服务、没有真实百度操作。Schema DDL 审核稿与应用实现拆为独立提交。

# G-Snipers 全域演示：SEM 虚拟数据包方案

## 当前交付

`scripts/build_sem_demo_fixture.py` 只在内存中生成确定性 JSON，可选原子写入本地文件。它没有数据库、HTTP、百度客户端、调度器或写回模块依赖，也没有任何“应用到环境”的参数。默认窗口固定为 2026-06-11 至 2026-09-08，共 90 天；重复运行生成完全相同的字节和 SHA-256。

```powershell
python scripts/build_sem_demo_fixture.py
python scripts/build_sem_demo_fixture.py --output .local/sem-demo/fixture.json
```

数据包专属标识是 `gsnipers-sem-demo-v1`，租户 ID 为 `990000001`，名称为“G-Snipers 全域演示”。所有行同时绑定租户和 fixture key；tenant 4 被列为受保护真实租户，生成器发现跨租户行会直接失败。

## 对象与情境

| 对象 | 数量 | 用途 |
|---|---:|---|
| 演示租户 | 1 | 独立“G-Snipers 全域演示”，不复用任何真实客户 |
| SEM 模块 | 1 | 仅声明演示租户的 SEM 工作区 |
| 外部账户 | 2 | 均为 `status=disabled`、`auth_mode=demo`，无凭据、不可调度、不可写回 |
| 计划 / 单元 / 关键词 | 4 / 8 / 24 | 两账户层级，固定保留 ID |
| 关键词日设备报告 | 4,112 | 90 天、PC/移动；含增长、骤降、预算压力、缺报及真实零值 |
| 地域报告 | 1,344 | 近 14 天、12 个词、4 个省份、2 类设备 |
| 星期×小时依据 | 2,688 | 近 14 天、12 个词、8 个代表小时、2 类设备；星期由日期确定 |
| 搜索词 | 48 | 已添加、未添加、不可添加三种状态 |
| 提醒 / 待办 / 操作历史 | 6 / 5 / 8 | 全部带“虚拟演示”或 synthetic 标记，不代表实际执行 |

场景包括稳定增长、近 7 天突然下滑、计划预算压力、最近 7 天缺报、资产存在但全窗口无报告、已有报告行的真实零值。电话按钮字段分为：完整可解析、仅 PC 可解析的部分覆盖、字段存在但不可解析，以及无报告时的 `no_data`。电话按钮点击不等于拨通电话或有效咨询；关键词报告花费不等于全部广告产品账户消耗。

## ID 与幂等规则

- 租户、账户、计划、单元和关键词使用 `990...` 保留段；报告与工作流对象使用 `1100...` 至 `1160...` 的稳定内部 ID。所有自然键和行 ID 都可重复生成。
- 操作历史的 `dedup_key` 由 fixture key 与虚拟关键词生成。
- 未来导入器只能在 `(tenant_id=990000001, fixture_key=gsnipers-sem-demo-v1)` 范围内 upsert 或清理。
- 本地 JSON 通过临时文件加原子替换写入；同一结束日期重复执行不会追加数据。
- 清理必须按数据包 manifest 的从属表顺序执行，并同时匹配租户和 fixture key。当前只输出清理计划，不输出或执行 SQL。

## 接口可见性审计

| 数据 | 预期读取位置 | 当前可见性 |
|---|---|---|
| 花费、展现、点击、CTR、设备 | `GET /api/v1/dashboard/cockpit` | 表结构兼容；默认账户范围只读 active 账户，disabled demo 账户不会进入结果 |
| 关键词列表 | `GET /api/v1/keywords/cockpit` | 资产可落表；报告关联仍受 active 默认账户范围限制 |
| 地域、星期×小时 | `GET /api/v1/keywords/cockpit/{keyword_id}` | 模型字段兼容；需演示读取隔离层提供 demo 账户范围 |
| 搜索词 | `GET /api/v1/search-terms/cockpit` | 模型字段兼容；需演示读取隔离层提供 demo 账户范围 |
| 提醒 | `GET /api/v1/alerts` | 表结构兼容，仍应由普通身份与租户权限读取 |
| 待办 | `GET /api/v1/sem/tasks` | 参数已限制为接口允许的三种 metric target；还受 `sem_tasks_enabled` 开关控制 |
| 操作历史 | `GET /api/v1/operation-records` | 表结构兼容；必须保留“虚拟历史，未调用百度写接口”标识 |

不能把演示账户改成普通 active 账户来绕过可见性限制。当前调度、同步、管理与写回入口普遍把 active 当作真实外部账户候选；在没有额外隔离字段和服务端门禁前，active demo 会扩大真实动作风险。

## 调度、写回与发布边界

数据包中的两个账户同时满足：disabled、demo auth mode、无 access/refresh token、`scheduler_eligible=false`、`writeback_allowed=false`。未来导入前还需要代码层做到：

1. 调度器、手动同步、OAuth 修复和所有百度 service 在选择账户时排除 demo。
2. 写回预检在检查 active 之前先拒绝 demo，且不能通过管理员密钥或 dry-run 参数绕过。
3. 演示读取通过明确的租户/账户 `data_mode=demo` 分支读取已有虚拟行，不改变普通租户的 active-only 语义。
4. API 响应显式返回 `is_demo=true` 和 fixture key；页面持续显示“全虚拟演示”。
5. 演示租户不能被复制、合并或重绑到真实百度 UCID。

本次没有数据库写入、迁移、部署、同步、补采集、AI 分析或真实写接口调用。

## 仍需数据库负责人确认

1. **隔离字段放置**：建议给租户和百度账户增加不可变 `data_mode`（`live|demo`），不要复用含义不稳定的 status 或 JSON 设置；是否需要 fixture ownership 表也需确认。
2. **账户可见与不可执行并存**：确认 cockpit 如何显式选择 demo 账户，同时保持调度、同步、OAuth、管理和写回永远拒绝。
3. **凭据非空约束**：`baidu_accounts.access_token_encrypted` 当前非空；demo 账户不应保存伪 token，需确认允许 NULL、拆分演示账户表，或采用完全独立的 fixture adapter。
4. **清理外键顺序**：需用实际 PostgreSQL schema 校验 manifest 的删除顺序、`sem_tasks` RESTRICT 关系和所有新增外键；不得直接在生产执行。
5. **fixture key 存储**：多数现有业务表没有 fixture key 列。需确认新增列、独立 schema，或专用演示数据库；在此之前无法安全做窄范围幂等 upsert/清理。
6. **ID 保留段**：确认 `990...` 段未被生产序列、外部百度 ID 或已有租户占用，并为数据库序列设置不会碰撞的策略。
7. **待办开关与身份授权**：确认演示账号的角色权限、`sem_tasks_enabled` 和只读身份配置；凭据不得进入夹具或交接文档。

数据库负责人完成以上确认后，下一阶段才能把 JSON 映射成受控导入器，并先在隔离数据库执行 dry-run、重复执行、接口读取和清理演练。

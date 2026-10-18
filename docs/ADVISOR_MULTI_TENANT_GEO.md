# GEO 顾问多客户拦截（G1 草稿）

**不可合并：合并即自动发布。草稿，不可合并直到用户批准。**

base `codex/production-geo`，核实 HEAD `5af737ab1b236aa19f86b070cf5a377659a6cd58`。
`production-geo-deploy.yml` 对该分支 push 无 paths 限制；合并就是发布。
本 PR 不执行迁移，不修改数据库权限、角色定义或 require_admin。

## 范围与矩阵

GEO 独立进程 `app/geo_main.py` 使用 `app/security/auth.py`，不挂 auth/accounts
管理和旧切换接口。选择客户/身份 JWT 由 SEM 提供，本服务只验证。
顾问每请求重读 User、Role、锁定和授权历史；业务 JWT 必须正确
aud/scope_kind/tid/gid/exp/auth_exp，原默认客户必须在有效集合。
未选择、空授权、旧无 gid、撤销、重授予后的旧 gid 均不能进入业务查询。
新功能开关关闭也不关闭 guard；旧 via 凭证一律 401。

共享 `advisor_scope.py` / `advisor_tenant_grant.py` 对齐 SEM 主版本。
GEO 适配仅在 `geo_advisor*.py`；permissions 只补 classifier 所需纯函数，
原菜单注册表、种子权限和非顾问 RBAC 使用方式保持原样。
`locked_until` 是既有迁移 0071 的字段映射，无新增列。

|入口|顾问规则|证据/限制|
|---|---|---|
|GET 项目/内容/列表/搜索/计数|当前 tid + GEO 模块 + 原菜单；要求 tenant_id|现有 SQL 仍按 tenant 过滤|
|GET 顶部 tenants|当前上下文客户过滤，绝不 NULL 全部|身份 token 在查询前拒绝；完整选项由 SEM auth/tenants 提供|
|GET job 轮询/列表（含 integration/read）|job 实际 tenant 反查 + 当前 gid 重验|不能通过额外合法 tenant 参数掩盖外客户 job_id|
|取消 job、生成/发布/入队/BackgroundTasks、其他写方法|403 ADVISOR_HIGH_RISK_WRITES_DISABLED，在 handler 前关闭|现有任务没有 grant 代次；即使未来 flag 为 true 也不会擅自开放|
|GET 对象过滤/详情/下载|project/task/ticket/audit/job/snapshot/patrol/business/unit/prompt/period/report 等实际 owner 校验|重复 tenant、次级 ID、指标 scope_key 同样检查；未知 *_id 关闭|
|静态 brief/channel/metric 目录|精确 GET 白名单 + 当前授权 + 模块/RBAC|不允许未选择客户的身份 token|
|未知路由/全局 usage/管理员候选接口|403 ADVISOR_ROUTE_UNAVAILABLE|已审核 GET 模板固定在 geo_advisor_routes.py，新路由默认关闭|
|持久交付存档和创建分享链接|顾问入口首期关闭|存档会返回不可撤回的永久 capability，不签发新链接|
|完成响应/下载/流式块|新 session 再读用户/角色/grant/模块，private,no-store|开始响应前失效返回拒绝；已开始流则停止交付后续块；已发数据不能收回|
|旧公开 OAuth 回调/公开分享|沿用原签名 state / share token 独立契约|顾问不能发起新 OAuth/分享写入；已有公开 capability 不承诺因 grant 撤销自动失效|
|管理员/超管/普通固定客户|原分支和原业务方法|缺表或权限不足不影响其正常请求|

任务首期不允许顾问发起，因此不添加 task gid 字段或后台任务权限；管理员/系统
任务仍按既有上下文运行。当前客户的旧任务只读不代表其获得顾问任务执行权限。

生产 GEO 没有 Alembic revision 白名单或按 revision 分支的结构门禁，
0108/0109 都不被代码拒绝；没有为了兼容而跳过任何原结构检查。
`demo_read_session.validate_demo_session` 校验的是独立演示库封存版本/回执/命名空间，
保持精确匹配，不能拿生产库的 0109 放宽此隔离边界。

## 验证与发布依赖

本地 `py ops/run_geo_checks.py`：环境白名单、合成配置、禁 dotenv；
新 HTTP/SQL 用例只使用 pytest 临时 SQLite，CI 执行现有临时 Postgres fixture。
包括两个授权客户、第三客户和另一个已授权客户跨当前上下文拒绝、重复 tenant、
猜测/轮询/取消 job、空集合、重授不复活、锁定/角色变化、旧 via、缺表/权限拒绝、
非顾问回归、查询后交付前撤销。跨前端验收由 F1/S2 联调承担，此 PR 不改界面。

依赖 S1 #695、S2 #699、E1 #696、E2 #698 和前端 F1 #697。
S1/E1/G1 兼容 guard 与 0109 建表/回填必须在同一个用户获批维护窗口紧接执行：
先部署三个 guard，再立即由 DB 负责人独立执行已审 0109 与冻结回填及 §8.3 核对；
提前通知顾问短暂 503。之后才开放选择/API/UI，试点和放量另批。
GEO 发布 workflow 是 `production-geo-deploy.yml`；本次不 dispatch。

回滚只选兼容 0109 且保留关闭式顾问拦截的代码，保留新表/ACL/授权历史，
不 downgrade/drop/stamp、不恢复 via，不回退到 NULL 全部可见的代码。

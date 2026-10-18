# 顾问多客户 SEM 兼容 guard（方案 B）

只供草稿 PR 审阅，未经用户批准不可合并或发布。正式表和不可逆撤销保护由 SEO 0109 独立交付；本分支不含迁移，不新增权限。

共享模型是 `app/models/advisor_tenant_grant.py`，共享角色 predicate / 显式范围 / 当次授权读取是 `app/security/advisor_scope.py`。不缓存名单，不从 JWT 信任角色或名单。`tenant_id=None` 对顾问只表示未选客户，不能表示全部。

S1+E1 guard 部署与 0109 建表、回填必须在同一个获批维护窗口紧接执行：先部署能识别 0109 的 guard，立即由 DB 负责人执行 0109 和回填，再做方案 §8.3 核对。提前通知顾问该几分钟窗口内会因缺表 503 短暂不可用，这是方案要求的关闭式设计取舍。随后发布账号名单及选择 API，最后前端。SEM 发布仅能由获批人员在 main 手动运行 `production-sem-backend-deploy.yml`，确认 `DEPLOY_SEM_BACKEND` 和当时生产后端分支完整 SHA。本次没有执行。

三个开关默认 false。旧账号切换 gate 关闭时列表为空、变更 410、旧 via 凭证 401。多客户入口开关关闭不影响受限 guard。高风险开关本身不能开放尚无 grant 绑定和最终副作用复核的路径。

## SEM 路由矩阵

具体可读路径由 `advisor_request.SEM_READ_ROUTES` 的精确正则枚举；未登记路径关闭式拒绝，即使只使用 require_auth 也不能绕过。

|入口|客户和对象范围|首期顾问动作|
|---|---|---|
|keywords 列表、cockpit、详情、export|显式 tenant 等于 tid；keyword_id 自然键与 tid 联查；账户/计划/单元过滤同样联查|只读，分页/count/export 沿用客户过滤|
|keywords 分类、暂停、writeback、批量|先拒跨客户和嵌套客户断言|写入尚未开放，403|
|manage 账户、计划、单元|账户 PK 和自然计划/单元 ID 反查且客户等于 tid|只读；所有资金/广告写关闭|
|writeback mode、列表、approvals、queue|显式 tenant 等于 tid，原查询含客户过滤|只读；decision/reconcile 等关闭|
|reports analysis/monthly/export/available-months|本分支没有报告 ID 下载路由，均以显式 tenant 查询|同步读取/导出；顾问只读 AI 缓存，不生成/写入/外部调用|
|结构、dashboard、alerts、画像、suggestions、搜索词、否词、操作记录、验证、leads 根列表|精确路由 + 显式 tenant + 模块 + RBAC|只读；未知子路径关闭|
|异步、流式、后台任务、助手、SEM tasks、持久导出|没有新增任务主体/grant 字段|不开放，403；系统调度身份不受影响|
|auth me/tenants/password/select-tenant|精确方法和路径白名单；业务凭证进入白名单仍校验 gid|仅本人；身份凭证不能访问 modules 或业务|

所有新请求读当前 User/Role、启用/锁定、授权代次。正在返回的同步响应无法收回；没有签出永久下载链接。新高风险路径仍需独立审查，不添加任务列、不扩大本方案 schema。

无表阶段拒绝顾问 clear_tenant 和改变已有用户顾问判定的角色单改/批改，防止回落到 NULL=全部。按 COMMON-2，普通角色编辑仅比较角色权限前后及 users，不读取授权表；非顾问请求及其管理操作不因缺表/无权限 503。顾问请求缺表/无权限仍然 503，表可读时授权历史仍作为受限标记。回滚必须保留受限 guard 和旧 via 拒绝，保留新表历史和 ACL，不得降到任意旧版本或执行 downgrade。

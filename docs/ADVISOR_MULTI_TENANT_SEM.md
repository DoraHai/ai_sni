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
|customer-profile|显式 tenant 等于 tid；模块与 RBAC 沿用同一 guard|顾问仅聚合读取及读取既有 AI 总结；无缓存或 refresh_summary=true 也不生成、不改客户缓存|
|结构、dashboard、alerts、画像、suggestions、搜索词、否词、操作记录、验证、leads 根列表|精确路由 + 显式 tenant + 模块 + RBAC|只读；未知子路径关闭|
|异步、流式、后台任务、助手、SEM tasks、持久导出|没有新增任务主体/grant 字段|不开放，403；系统调度身份不受影响|
|auth me/tenants/password/select-tenant|精确方法和路径白名单；业务凭证进入白名单仍校验 gid|仅本人；身份凭证不能访问 modules 或业务|

所有新请求读当前 User/Role、启用/锁定、授权代次。正在返回的同步响应无法收回；没有签出永久下载链接。新高风险路径仍需独立审查，不添加任务列、不扩大本方案 schema。

无表阶段拒绝顾问 clear_tenant 和改变已有用户顾问判定的角色单改/批改，防止回落到 NULL=全部。按 COMMON-2，普通角色编辑仅比较角色权限前后及 users，不读取授权表；非顾问请求及其管理操作不因缺表/无权限 503。顾问请求缺表/无权限仍然 503，表可读时授权历史仍作为受限标记。回滚必须保留受限 guard 和旧 via 拒绝，保留新表历史和 ACL，不得降到任意旧版本或执行 downgrade。

## S2 账号与会话协议

账号列表、详情、新建/编辑响应包含 is_advisor、tenant_ids、default_tenant_id、grants_version；非顾问列表为空且版本为 null。版本严格按 COMMON-2 的 v1/default/有效 grant ID 字符串排序计算 SHA256 前16位，不存库。

维护窗口缺表/无读权限时，管理员账号列表/详情及只改名字等响应仍可用；顾问投影附 grants_available=false、grants_error_code=ADVISOR_GRANTS_UNAVAILABLE，tenant_ids=[]、grants_version=null 表示授权数据暂不可读，不代表实际撤销。此投影不签发可写版本；名单变更仍428/503拒绝，顾问本人业务仍503。新入口必须等0109与授权核对完成后开放。

正常投影显式 grants_available=true。只对503且detail.code=ADVISOR_GRANTS_UNAVAILABLE应用上述只读投影，其他错误照常抛出，不掩盖无关服务故障。

顾问新建必须至少勾一个客户，默认取首个；PATCH 只要显式带 tenant_ids/default_tenant_id 就必须提供 expected_grants_version，缺失428，持有 users 行锁后重算不符409。取消当前默认时同时给出新默认。名单去重、严格正整数且所有客户存在、至少有角色可用模块；整批原子授予/撤销，重新授予必新行。旧 tenant_id 字段不能绕开名单/版本校验。只改名字/密码无需版本，clear_tenant 和角色转换仍冻结。

全局账号/角色管理和顾问名单变更统一要求 settings.accounts=edit 且 settings.customers=edit，避免仅有账号维护权的角色先给自己加权再变更授权。名单变更另锁定实名操作者及目标账号（按 ID 顺序），重读启用、锁定、未绑定客户与双权限；API Key 不能代替实名超级管理员。内置管理员沿用有效权限补齐规则。沿用现有管理审计事务和结构化授予/撤销事件，不创建额外审计表、不增加权限。

POST /api/v1/auth/select-tenant 只接受 tenant_id，本人身份/有效客户凭证可选择最新授权内客户；再次持有 users 行锁后重验账号/角色/原 gid/有效名单/模块。sub不变、不改默认、不延长原 auth_exp，响应 access_token/token_type/tenant_id/tenant_name/expires_at。成功/拒绝记录结构化业务事件，不复用旧切换审计表，不记录 JWT。限频为每个 worker 每用户每分钟10次（含拒绝），内存状态有上限和过期清理；这是进程内限频，不声称跨 worker 的全局限频。

新入口关闭：选择404、名单写入422，detail.code=ADVISOR_MULTI_TENANT_DISABLED；受限 guard 始终生效。原身份 token 可用于重新选择，已撤销的业务 token 不能借选择接口降级为身份 token。

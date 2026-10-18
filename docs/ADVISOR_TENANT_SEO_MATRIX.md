# 顾问多客户：SEO 首期边界（草稿，不可合并直到用户批准）

合并到 codex/production-seo 即自动发布。此提交不执行迁移、不开放新选择客户入口。
SEM 登录/名单管理/选择客户由独立 SEM PR 提供；SEO 只验签并重读 User、Role、最新授权。
新功能开关关闭仍强制 guard；旧 #657 via 凭证始终 401。
SEO 服务只挂载 SEO 路由，不挂载 auth/account-links/linked-accounts/switch-account；
因此它没有可调用的旧切换入口。共享 legacy validator 对一切 via 关闭。

|入口|范围与对象复核|首期顾问行为|
|---|---|---|
|站点 selector、/seo/sites、/workbench/sites|每请求 gid/tid + 模块；SQL 按 tenant_id 过滤|只读；仍保留 seo.assets 或 workbench RBAC|
|站点/页面/关键词/内容/截图/发布详情/变体/会话|请求所有重复 tenant_id 必须一致且等于当前 tid；路径和 query 中对象 ID 反查实际 tenant；现有站点/参与者检查保留|只读；A token 即使也授权 B 仍不能访问 B|
|消息与内容工作流|0108/0109 兼容；会话 scope 用当前 grant，不能用默认客户代替当前客户；原站点分配和参与者检查保留|读取允许，发送/确认/推进暂拒|
|列表/搜索/分页 count/聚合/轮询|显式 tenant 参数 + grant；SQL 原有 tenant 条件；未知路由/未知对象关闭式拒绝|只读；省略 tenant 不回落全量|
|导出/下载/截图图片|已有结果的每次 HTTP 请求重验 grant，复核实际对象所属客户；无永久直链增量|允许既有同步读取；持久导出创建拒绝|
|发布/供应商推送/采集/生成/取消/批量写/BackgroundTasks|所有非 GET/HEAD/OPTIONS 业务请求在 handler 之前拒绝，ADVISOR_HIGH_RISK_WRITES_DISABLED|不入队、不发起副作用；高风险开关本轮不能单独解除拒绝，须另行验收|
|未知接口/流式入口|身份 JWT 仅精确会话白名单；未审业务路径拒绝|不依赖前端隐藏|

非顾问保留原有 RBAC、固定客户与 API Key 路径。0071 已有 locked_until 只补 ORM 映射。
历史纳管用户失去顾问角色后关闭式拒绝；平台账号管理员保留已有权限语义。
缺表/读取失败：顾问 503；普通固定客户与管理员不依赖新表即可工作；
无客户的非管理员若不能证明没有受限历史，也 503（方案 5.1 的要求）。

兼容验收：0108 + 缺表对顾问 503；0109 + 旧顾问 JWT 409；
0109 + 新 JWT 重验 gid；缺表/无权限关闭式；两 revision 均执行全部旧结构检查。

GEO 发布单元是 codex/production-geo 的 production-geo-deploy.yml，push 自动发布；
main 也保有该 workflow。SEO 服务部署不会重启/发布 GEO，GEO guard 是放量前独立依赖，
本 PR 不宣称 GEO 已保护，不另开混入 GEO 业务改动的分支。

上线顺序：三服务兼容 guard → E2 文件/0109 head 检查 → 用户独立批准 DB 负责人建表/回填/ACL
→ SEM API → 前端 → 用户批准小范围启用。E2 base 为 E1，E1 合并并发布后再改 base。
回滚仅退到保留 guard 且兼容 0109 的代码；不 downgrade、drop、清历史或恢复旧 via。

# Readiness 查询修复

独立分支 codex/geo-readiness-export-readonly-20260906，基准5df03e0。只修批准的 readiness 范围；未推送或部署。

GET /api/v1/geo/onboarding/readiness 复用GEO开通/到期资格依赖及 READ ONLY / REPEATABLE READ 会话。移除查询路径的历史事实business_id补绑与commit；原统计字段保持，新增unassigned_onboarding_facts（数量、automatic_assignment=false、说明）报告历史未关联资料，不自动回填。

正常onboarding提交的attach_orphan_onboarding_facts调用未改，仍在显式写事务中处理事实归属；本次未修改共享认证及其他旧GET。

真实本机隔离PG验证：现有默认业务、孤立开户事实、非开户事实、停用事实、其他客户及已有归属同时存在时，HTTP GET成功且所有事实行逐字段不变，报告2条。随后仅在独立fixture写事务调用既有补绑函数，确认只改变符合条件的2条，GET报告归零。未开通客户403。fixture身份不等于真实JWT。

readiness新增PG、onboarding纯函数、既有HTTP资格/分页测试合计22 passed。最终整包全量验证在export拆分后记录。

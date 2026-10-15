# 顾问多账号切换

一个账号仍只绑定一个客户。实名平台管理员（`tenant_id IS NULL` 且 `settings.accounts=edit`）建立、扩充或解除关联组；成员必须启用、绑定非空且互不相同的租户、有 SEO 或 GEO 顾问编辑权，且无 `settings.*` 编辑权。建组前管理员须核实各账号属于同一位顾问。

`GET /api/v1/auth/linked-accounts` 只列有效的其他成员。`POST /api/v1/auth/switch-account` 对当前账号先做无锁资格和关联预检，再以来源账号为键获取事务 advisory lock，并对来源和目标关联行取 `FOR SHARE` 锁；每来源账号每分钟最多 10 次，429 不写审计。目标停用、锁定、迁移租户或失去顾问资格均拒绝。成功不更新目标 `last_login_at`。

切换 JWT 带 `via=advisor_switch`、`src`、`grp`，有效期 2 小时。每次鉴权复核来源和目标均启用、仍在同组、租户与关联时的快照相同且仍有顾问资格；解除关联或停用来源会令派生会话立即失效。普通密码登录 JWT 仍沿用现有有效期。前端替换 token 后清空旧租户上下文与未提交的 SEO 改写文本、SEM 构建交接暂存，重载顾问工作台。持久审计记录建组、扩组、解除和切换的操作者、组、原因、IP、User-Agent 和时间。

## DB 审核与发布顺序

本分支的 `migrations/pending-db-review/advisor_account_links.sql` **只是审核草案，不能直接执行**；它仅新增关联表与审计表，不挂在本分支 Alembic 链上。三服务共用数据库，DB 负责人须核实现场 head，在其后分配正式修订号并纳入统一迁移链。SEO 的精确修订门禁（`app/seo_main.py`、`app/api/seo.py`、`app/api/seo_messages.py`、`app/seo_content_workflow.py`）及其他同类门禁须先同步白名单并发布代码，之后才能应用迁移。当前代码已将 SEO 0107 纳入相关确认和消息门禁；未来正式修订号未确定，不能提前列入。

SQL 草案使用租户快照、`timestamptz`、审计状态 CHECK 与明确的用户外键删除语义。降级删除两张表会永久丢失审计，需单独批准。代码早于建表部署时，已登录且具顾问资格的 `/linked-accounts` 和 `/switch-account` 对 PostgreSQL 未定义表错误返回 503。整个流程须走 DB 审核；此开发任务不连接真实数据库、不执行迁移。

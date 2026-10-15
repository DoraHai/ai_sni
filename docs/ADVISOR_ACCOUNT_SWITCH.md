# 顾问多账号切换

一个账号仍只绑定一个客户。实名平台管理员（`tenant_id IS NULL` 且 `settings.accounts=edit`）建立、扩充或解除关联组；成员必须启用、绑定非空且互不相同的租户、有 SEO 或 GEO 顾问编辑权，且无 `settings.*` 编辑权。建组前管理员须核实各账号属于同一位顾问。

`GET /api/v1/auth/linked-accounts` 只列有效的其他成员。`POST /api/v1/auth/switch-account` 对当前账号先做无锁资格和关联预检，再以来源账号为键获取事务 advisory lock，并对来源和目标关联行取 `FOR SHARE` 锁；每来源账号每分钟最多 10 次，429 不写审计。目标停用、锁定、迁移租户或失去顾问资格均拒绝。成功不更新目标 `last_login_at`。

切换 JWT 带 `via=advisor_switch`、`src`、`root_src`（最初密码登录账号）、`grp` 和 `auth_exp`（原密码登录会话到期时间）。每次切换的到期时间为 `min(当前时间+2小时, auth_exp)`，链式切换不能延长原会话。SEM、SEO、GEO 每次鉴权均复核来源、根来源和目标启用、仍在同组、租户与关联快照相同且仍有顾问资格；三个服务均发布复核代码后，解除关联或停用来源会令派生会话在下一次请求时失效。普通密码登录 JWT 仍沿用现有有效期。前端替换 token 后清空旧租户上下文与未提交的 SEO 改写文本、SEM 构建交接暂存，重载顾问工作台。持久审计记录建组、扩组、解除和切换的操作者、组、原因、IP、User-Agent 和时间。

## DB 审核与发布顺序

两张表由正式迁移 `0108_advisor_account_links`（`down_revision=0107_seo_site_delete`）创建。三服务共用数据库，共享迁移链位于 SEO 分支（`codex/production-seo` 的 `migrations/versions/20261015_0108_advisor_account_links.py`），本分支 Alembic 链不包含 0107，因此不在此重复迁移文件。同一 SEO 提交已把 0108 加入 `app/seo_main.py` 的两个兼容集合与结构检查集合，以及 `app/api/seo.py`、`app/api/seo_messages.py`、`app/seo_content_workflow.py` 的白名单。迁移只建表；`sem_app` 的默认权限会给 `sem_runtime` 自动授予增删改查，须由 DB 审核包中的精确权限脚本在同一事务内收回多余权限：关联表仅 SELECT/INSERT/DELETE 与 `UPDATE (created_at)`（`FOR SHARE` 需要），审计表仅 SELECT/INSERT，序列不授权。迁移须经 DB 审核后由负责人执行，开发分支不得自行执行。

发布顺序：先发布带切换 JWT 复核的 SEO 和 GEO 服务，再由 DB 负责人执行审核后的正式迁移，最后发布 SEM 并开放切换、建立关联组。任何服务缺少复核时，不能开放切换；否则该服务在切换 JWT 到期前无法立即撤销派生会话。

迁移使用租户快照、`timestamptz`、审计状态和动作 CHECK 与明确的用户外键删除语义。降级删除两张表会永久丢失审计，需单独批准并先备份。代码早于建表部署时，已登录且具顾问资格的 `/linked-accounts`、`/switch-account` 和管理员关联接口对 PostgreSQL 未定义表错误返回 503，SEO/GEO 对切换 token 返回 401。

# 渠道稿审核提交后的响应序列化修复

日期：2026-10-12。独立基线 `080d75f923894fc0a10cb23171f0feeca4f7c2f1`。被中央运行引用的旧工作树保持冻结只读。

## 缺陷及最小修复

基线 `app/api/seo.py:9071` 的 `review_distribution_variant` 在审核事务提交后立即调用同步 `_distribution_variant_payload`，其第 6496 行读取 `row.updated_at`。该字段由 SQL 表达式 `onupdate=func.now()` 更新，提交后可能处于过期状态；即使生产会话采用 `expire_on_commit=False`，读取它仍会尝试隐式异步查询并触发 `MissingGreenlet`。

故障结果是**审核已提交，HTTP 响应却是 500**。本批在 SEO 自有隔离 PostgreSQL 上用真实 ASGI/JWT 请求重现了通过/退回两种决策，并分别使用 `expire_on_commit=False/True`：四种组合均先确认数据库已提交，再确认旧代码返回 500。没有访问中央数据库，也没有重放中央已提交的审核。

修复仅在该 endpoint 的现有 `await session.commit()` 后，分别 `await session.refresh(row/content/connection)`，显式加载同步响应需要的三个对象。未改变 commit、ORM 过期机制、审核状态机、权限或来源校验，没有新增数据库结构。全量刷新兼容默认会话的 SQL 生成字段过期，也兼容整对象在 commit 后过期的会话。

## 验证内容

- **真实请求/真实 commit**：使用完整 `/api/v1/seo/content-distribution/variants/{id}/review` 路径，执行原生 scoped auth；不替换 commit/flush/refresh，不绕开数据库。
- **通过/退回返回 200**：覆盖两种 `expire_on_commit` 配置，响应包含完整既有字段集合、时间字段及可 JSON 序列化的审核结果。
- **提交后的状态一致**：另一个数据库会话验证实际状态、审核人和审核时间。已确认母稿的通过结果能通过原生 `load_source`；退回结果仍被 `review_required` 拒绝。
- **没有重复审核写入**：原生渠道稿审核将审核信息保存在 variant 行，未提供独立事件表。测试仅在随机 schema 中安装事务性审计触发器，确认一次请求恰好一次持久审核 UPDATE；重复请求返回 409，审计数量仍为 1，审核时间不变。该测试触发器不属于生产代码或迁移。
- **拒绝项不写审核**：匿名、失活账号、只读角色、错客户/站点、旧母稿/旧渠道稿返回拒绝状态，variant 保持 pending，测试审计数量为 0。
- **审核与客户确认分开**：现有接口允许审核渠道稿；若母稿没有有效客户确认，即使渠道稿审核返回 200，`load_source` 仍以 `confirmation_required` 拒绝进入可发布来源。本批不把审核通过当作客户确认。
- 同步回归浏览器公众号映射、原生来源各门禁和既有分发测试。

测试范围、XML 哈希、源码提交及文件摘要见 `SEO_REVIEW_RESPONSE_ACCEPTANCE_EVIDENCE.json`。旧代码复现报告中的四个预期失败单独留档，不混入修复后的验收结果。

## 验收交接

中央可将 SEO 原生源码根切换到本批最终冻结版本，核对已经提交的审核结果；不得因旧响应 500 自动重新审核。新的通过/退回交互可在独立验收环境继续验证。

仅本地提交：没有 GitHub 操作、推送、部署、生产 DDL、真实平台调用；没有修改共享 auth/main、中央、SEM、GEO 或历史冻结树，也没有访问中央 55463 / GEO 55527 数据库。此前历史 schema 缺失异常不属于本修复。

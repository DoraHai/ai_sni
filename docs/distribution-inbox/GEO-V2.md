# GEO 多号通 v2

GEO 使用 SEO 唯一 revision `0110_distribution_inbox` 的两张共享表；本分支不提供迁移、不自动建表。双方同 database/schema 的前提由派单方 2026-10-19 20:44 的决定确认。上线仍须另行批准，先按 SEO 发布步骤建表，再发布两服务与客户端；本轮只交草稿 PR。

`GET /api/v1/geo/distribution/v2/publications`、`POST /api/v1/geo/distribution/v2/receipts/{uuid}/label|unlabel` 使用既有人员业务 JWT；GEO 顾问必须选择已授权客户。精确路径、原始路径、唯一查询参数和严格 JSON 均检查。普通客户账号、API key、仅有 settings.accounts 编辑权的角色不能管理。人员管理员只认系统角色“管理员”。

写入先按 ID 顺序锁所有者/操作者，再锁收件记录；角色、客户授权、模块、项目及稿件权限在事务内刷新、锁定并再次核对。顾问继续受既有总写开关约束。项目可空；范围待补仅所有者及系统管理员可读。项目存在时必须有效、属于目标模块、绑定业务无歧义且当前分配给顾问。没有稿件即可保存。可选 `articleId` 表示 GEO 内容任务 ID，`articleVersion` 是最新 master 的 version_no，`articleDigest` 是正文 UTF-8 SHA256；必须审核 approved、同客户同项目、业务链有效。无原生渠道、公众号或平台账号依赖。

原始事件及所有者不改；已标不同客户或模块必须先在原模块撤销，再标新目标，第二步失败仍为待标。原目标失权需要系统管理员代撤；同目标修改也复核原、新项目。修订历史存于共享收件表，个人投影仅输出动作与时间。成功链接在客户/模块/范围内排他；冲突只给固定错误，摘要碰撞给固定人工核对错误。撤销恢复未标容量前检查硬上限，不删除历史 ACK。

发布记录直接投影收件表，标“外部回传”。不插入 GeoPublication、不创建稿件、渠道或占位账号、不改原生发布状态、绩效、任务或验收；无稿件显示 unlinked，有固定稿件引用显示 unavailable，不声称正文核验通过。不自动抓取 URL，不提供导出。

GEO 独立前端 `#/distribution-inbox` 在客户 bootstrap 与项目选择器外。收件箱使用独立 fetch 模块及已有身份会话，GEO-only 与零授权顾问能进入并配对；无目标时提示“暂无可标注的客户，请联系超管授权”。只有明确业务操作才换取所选客户业务 JWT；不改变壳的当前客户，不把业务 JWT 当身份凭证，不注入 tenant/project、不回退 API key。切身份、权限刷新、换客户和卸载会清空列表/配对码并拒绝迟到响应。

页面保留配对、待标客户、设备三个区域；已标记录可撤销、同目标补范围/稿件/发布账号，跨模块改标先撤销。可选项折叠；系统管理员可筛选离职所有者。外部记录页位于 `#/geo/external-publications`。旧版稿件派发保留独立兼容区，协议与服务不变。

设备配对、猜码限速、接收与 ACK 由 SEO 承担，具体限制见随附契约。已知码持久限速，未知码进程内有界 IP/摘要兜底不宣称跨 worker 全局 IP 防护。本分支不增加开关、env、权限、部署流程或生产操作。

验证：`python ops/run_geo_checks.py --postgres` 在空白隔离 loopback geo_ci 数据库运行全部 GEO 测试；`--distribution-report` 也强制包含 v2 用例。测试直接执行 SEO 迁移同一 DDL，逐项对照 GEO ORM 的列、约束、索引。HTTP 测试使用合成 JWT/客户/事件，覆盖越权、GEO-only、修订并发、去重、跨模块状态、撤销、权限变化回滚与缺表 503。前端使用 `node --test frontend/tests/geo*.test.mjs` 及独立 GEO build。

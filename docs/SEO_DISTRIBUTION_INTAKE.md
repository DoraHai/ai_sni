# SEO 发布队列只读候选接口

本批基线为 `12ce7fb31f61ca4c7a7ab24569599ca6ae97b38d`。此前发布监测的 198 项验收证据保持不变。本批只增加 SEO 原生来源适配器、专项测试和本文档，没有新增生产 HTTP 路由、数据库结构或发布操作。

## 服务端调用契约

```python
from app.seo_distribution_sources import list_intake_candidates, load_intake_candidate

page = await list_intake_candidates(
    session, actor_user_id, tenant_id, scope_id, 'wechat-article',
    after_variant_id=None, limit=50,
)
candidate = await load_intake_candidate(
    session, actor_user_id, tenant_id, scope_id, variant_id, 'wechat-article',
)
```

平台仅支持既有 `wechat-article`（微信公众号文章）与 `xiaohongshu-image`（小红书图文）。网站发布入口仍未接入。`scope_id` 是 SEO 网站 ID，账号必须取自可信身份认证结果。

列表固定返回 `{items: [...], next_cursor: int | null}`；点查返回相同的单条元数据或 `null`。每条只含以下五字段，不返回标题、正文、图片清单、URL、存储路径或凭据：

| 字段 | 约定 |
| --- | --- |
| `variant_id` | 正整数渠道稿 ID |
| `draft_version` | `seo-draft-` 加 64 位 SHA-256；符合 `[A-Za-z0-9_-]{1,100}` |
| `source_revision` | 仅 `ready` 时返回既有 `load_source` 的原始版本号，其他状态为 `null` |
| `readiness` | `ready` / `awaiting-review` / `awaiting-adaptation` |
| `reason` | 固定 ASCII 原因码，符合 `[A-Za-z0-9_]{1,64}` |

`draft_version` 包含渠道稿及母稿的内容/版本、图片素材集及清单；不包含审核状态、审核人、审核时间、备注、更新时间或连接状态。单纯待审→通过、退回→再审不会换版；正文、母稿版本、图片素材替换会换版。该字段不是发布授权。中央应以来源身份加 `variant_id`、`draft_version` 更新同一条队列记录，不能用 `source_revision` 作为待审草稿的身份。

## 候选与分页规则

- 每个母稿、渠道连接只选择当前最新 revision（`revision_number DESC, id DESC`），然后检查完成状态。最新稿仍在生成时，不回退到旧的已审稿。
- 原生已成稿状态集合为 `draft / pending_review / approved / rejected / published`；`generating / queued / failed` 及未知状态不列入。`published` 仍按现有 `load_source` 审核门禁判断，不自动视为可重复发布。
- 仅文章渠道稿、当前客户/站点/平台和同客户连接。过期母稿版本、停用连接、缺确认等仍返回对应候选和等待原因。
- 按 `variant_id ASC`，严格 `id > after_variant_id`。首轮 `after_variant_id=None`；游标若提供必须是正整数。`limit` 仅接受整数 1–50（拒绝 bool、float、字符串）。
- 查询多取一条判断后续页：有后续才返回本页末 ID，否则 `next_cursor=null`，包括恰好满页且没有后续的情况。
- 中央到尾需回到 `None` 重新扫描，才能更新旧 ID 的审核状态。点查用于清理被新稿替代的旧 pending 项。
- 点查仅在 ID 不存在、不属于当前范围/平台、不再是 latest、或尚非已成稿时返回 `null`。待审核/待适配返回元数据；失权、结构/数据库错误绝不能按失效记录删除。

## 状态与错误

| readiness | reason | 原生依据 |
| --- | --- | --- |
| `ready` | `ready` | 当前 `load_source` 全部门禁通过，来源版本完全相同 |
| `awaiting-review` | `review_required` | 母稿或渠道稿尚无完整有效审核 |
| `awaiting-review` | `confirmation_required` | 当前母稿尚无有效客户/顾问代确认 |
| `awaiting-adaptation` | `connection_unavailable` | 来源连接停用或 API 连接未就绪 |
| `awaiting-adaptation` | `source_stale` | 母稿/渠道稿版本不匹配 |
| `awaiting-adaptation` | `assets_unavailable` | 图片未冻结或与稿件不符，或文章含尚未支持的素材 |
| `awaiting-adaptation` | `content_invalid` | 标题/正文缺失、超限或未通过平台格式校验 |
| `awaiting-adaptation` | `keywords_invalid` | 关键词归属或内容覆盖不满足现有门禁 |

按既有 `load_source` 校验顺序返回首个等待原因，不宣称枚举了所有阻塞项。只有表中已知业务 409 映射为等待状态。

失权（403）、范围错误（403/404）、站点/服务停用（409）整页拒绝。数据库/结构/连接错误返回脱敏的 `503 seo_distribution_source_unavailable`。参数不合法为 422。读取期间稿件/素材/latest 变化则 `409 seo_distribution_source_changed`，中央应重读该页，不推进游标或删除旧项。

## 事务、权限及集成依赖

每次调用先核查当前用户、角色、顾问分配、客户/站点、SEO 模块有效性，完成读取后再次核查（空页也核查）。使用调用方现有 `AsyncSession` 的标量查询及 `no_autoflush`；不新开连接、不读 ORM 缓存、不 flush/commit/执行 DDL、不访问平台。调用方使用短 READ COMMITTED 事务，不与来源写操作混用。每条 ready 的准确内容仍须在实际创建、派发、回传时通过既有 `load_source` 重新授权。

实际联调依赖：

1. 中央 3.0 按上述两个函数接线，并实现游标到尾重扫、同版本状态更新、旧候选点查和失败重试；本批不修改中央代码。
2. 使用已授权的客户、SEO 站点、实名用户及当前顾问分配；真实用户凭据不进入文档或测试证据。
3. 小红书图文依赖现有三张素材表及不可变约束。未安装时按结构错误拒绝，不能降级成“待适配”。本批不会安装这些表；生产结构和部署仍需既定审批。
4. 真实平台发布未验收，站点截图不等于内容验证、搜索收录或效果提升。SEM AI 控制保持关闭。

测试使用本机隔离 PostgreSQL 随机 schema、合成客户/稿件/图片、真实 JWT 和 ASGI 测试入口；没有真实平台调用。测试数量、源码提交和报告哈希见同目录 `SEO_DISTRIBUTION_INTAKE_EVIDENCE.json`。

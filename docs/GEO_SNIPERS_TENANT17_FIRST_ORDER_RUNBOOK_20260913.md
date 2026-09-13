# SNIPERS GEO 正式首单 Runbook（tenant 17）

> 基线：`codex/production-geo` `a344f2e921362c71b819ab00812e2e20c83bd123`
> 日期：2026-09-13
> 本文只描述准备顺序和停止条件。本次不登录、不写库、不配置渠道、不生成、不审核、不发布。

## 1. 唯一对象与已知状态

本轮正式首单只允许使用 `tenant_id=17`。不得借用历史客户、演示租户或任务 14。

| 项 | 已确认状态 |
| --- | --- |
| 客户 | SNIPERS 自有正式客户；系统主键 `tenant_id=17` |
| 模块 | GEO 已开通且长期有效 |
| SEM / SEO | 未开通；本轮不得新增相应权限或数据 |
| 演示 | 未开通；不得写入 demo 标识、演示绑定或 synthetic 数据 |
| 账号 | 尚未配置 |
| 审核权限 | 尚未配置 |
| 官网渠道 / Webhook | 尚未配置 |

仍需真人提供并确认：账号用户名、显示名与初始密码；客户在系统中的准确显示名；法定/对外品牌名；官网域名；首个业务/产品；目标受众与场景；竞品；禁止表述；CTA；首个优化单元与问题；至少三条可核验原子事实及各自公开来源；CMS Webhook 地址、认证头或 HMAC secret、请求方法、成功响应格式。任何值都不得从“SNIPERS”字样或历史租户推算。

## 2. 上线前硬前置

1. PR #574 已合并只说明 0099 迁移代码进入 `production-seo`，不等于数据库已经迁移。数据库协调人必须另行确认共享库唯一 `alembic_version=0099_geo_review_audit`，且 `public.geo_content_tasks.review_audit` 为 **nullable JSONB、无默认值**。
2. 只有第 1 项通过后，才可合并并部署 PR #575。部署后核对 `/health/geo` 成功，并确认运行代码 SHA 包含 #575 head。
3. #575 上线前不得开展首单审核或发布。旧的 `review_status=approved` 无完整事件依据时必须按失败关闭处理，重新提交、重新审核。
4. 本文后续每个写步骤均须由明天的管理员/操作人明确执行；出现 tenant 不是 17、GEO 权益非 active、演示标识、数据库不是 0099、响应 5xx 或字段与本文不符时立即停止。

## 3. 管理员创建“同人操作 + 审核”账号

页面入口：`/settings/accounts`。API 仅作为字段对照；创建动作需要已有管理员身份。

### 3.1 创建最小角色

先 `GET /api/v1/roles`，确认没有等价角色；不要猜 `role_id`。如需新建，调用 `POST /api/v1/roles`：

```json
{
  "name": "GEO首单操作审核",
  "description": "仅操作并审核 tenant 17 的 GEO 首单",
  "permissions": {
    "geo.content": "edit"
  }
}
```

角色名称只是管理员可读标签，授权依据是 `permissions.geo.content=edit`。该权限允许同一登录账号完成内容操作、独立提交审核和审核决定。不要添加 `settings.accounts`、任何 `seo.*`、SEM 菜单、`onboarding` 或其他客户权限。若还要运行 GEO 诊断，另行评审是否增加 `geo.diagnosis=view`；官网首单链路本身不需要它。

停止条件：角色响应未返回新 `id`；权限被清洗为空；出现额外菜单权限；系统已有角色权限更宽且无法收窄。

### 3.2 创建并绑定账号

使用上一步实际返回的角色 ID 调用 `POST /api/v1/users`：

```json
{
  "username": "<管理员与实际操作人确认的用户名>",
  "password": "<仅通过密码管理渠道交付的初始密码，至少8位>",
  "display_name": "<实际操作/审核人姓名或明确工号>",
  "role_id": "<上一步真实返回的正整数ID>",
  "tenant_id": 17
}
```

不要把密码写入本文、工单或聊天记录。创建后由该真人登录，再只读调用 `GET /api/v1/auth/me`，逐项确认：

- `user.id` 是正整数，后续将成为提交和审核事件的真实 actor；
- `user.tenant_id=17`；
- `user.role_label` 与所建角色一致；
- `permissions.geo.content=edit`；
- tenant 17 的 GEO entitlement 为 active，且没有 SEM/SEO 或 demo 开通结果。

停止条件：`tenant_id` 为 null 或非 17；使用共享/机器人账号；角色不明确；账号被停用；权限含 SEM/SEO；前端能切换到其他客户。

## 4. 品牌、业务、单元、问题与事实的配置顺序

统一从 `/geo/brand` 和 `/geo/tasks` 操作；所有 API 请求显式携带 `tenant_id=17`。保存每一步真实返回的 ID，后续只引用返回值，不预填或猜测 ID。

### 4.1 优化业务与品牌画像

先创建一个 `POST /api/v1/geo/optimization-businesses`：

```json
{
  "tenant_id": 17,
  "name": "<首个真实业务/产品线名称>",
  "description": "<业务边界>",
  "sort_order": 0,
  "profile": {
    "product_name": "<准确对外品牌或产品名>",
    "website": "<官方HTTPS网址>",
    "summary": "<经负责人确认的简介>",
    "industry": "<行业>",
    "audience": "<目标受众>",
    "scenarios": ["<真实适用场景>"],
    "geo_scope": "<地域/语言范围>",
    "capabilities": ["<已证实能力>"],
    "qualifications": ["<可举证资质>"],
    "honors": ["<可举证荣誉>"],
    "competitors": ["<确认纳入比较的竞品>"],
    "recommend_reasons": ["<有事实支撑的推荐理由>"],
    "banned_claims": ["<禁止生成或需法务复核的表述>"],
    "cta": "<批准使用的行动引导>"
  }
}
```

空缺字段保持空，不补写宣传性结论。停止条件：官网、品牌、业务边界未由负责人确认；资质、荣誉或效果描述没有来源。

### 4.2 优化单元

用上一步真实 `business_id` 调用 `POST /api/v1/geo/optimization-units`：字段为 `tenant_id=17`、`business_id`、`name`、`keyword`、`description`、`sort_order`。首单只建一个清晰主题单元。

停止条件：业务不属于 tenant 17；关键词同时混入多个产品/意图；单元边界无法由负责人解释。

### 4.3 首个问题（prompt）

调用 `POST /api/v1/geo/prompts`，至少填写：`tenant_id=17`、真实 `unit_id`、完整自然语言 `question`、`source=manual`、`language=zh-CN`、`market=cn`、`priority`、`question_group`、`tags`、`demand_note`、`is_brand_probe`。

`is_brand_probe` 必须由问题文本和本次观测目的决定，不能为了得到更好指标而改标。首单正式内容优先选择真实客户问题，而非专门点名品牌的探测题。

### 4.4 至少三条核验事实

每条事实先 `POST /api/v1/geo/facts`，使用 `tenant_id=17`、真实 `business_id`、`title`、原子化 `statement`、`fact_type`、`source_name`、公开 `source_url`、`observed_at`、合理的 `expires_at`、`trust_level=needs_review`、`author_name`。不得直接创建为 `verified`。

随后逐条由真人阅读来源并调用 `POST /api/v1/geo/facts/{fact_id}/verify?tenant_id=17`，填写连续原文 `excerpt`、可复查的 `excerpt_locator`、`source_url` 和必要说明。跨语言材料还须提交已审阅的完整原文/来源快照及 `verified_translation`。陈述变更后必须重新核验。

停止条件：少于三条 verified 事实；来源 URL 不公开或无法定位；陈述超过一个原子结论；数字、案例、资质、荣誉或效果没有直接依据；过期事实仍被使用。

## 5. 官网 website Webhook 配置顺序

首渠道选择 `website`：它是 SNIPERS 自有发布面，责任边界和公开 URL 最清楚；通用 Webhook 不依赖第三方 OAuth，最适合完成首个“单渠道发布 → 公开核验 → 证据回填”闭环。

1. 在 `/geo/publishing` 先只读 `GET /api/v1/geo/publishing-channels?tenant_id=17`。列表中的虚拟默认项不等于已持久配置，记录实际官网渠道 ID；没有实际 ID 时再创建。
2. `POST /api/v1/geo/publishing-channels`：`tenant_id=17`、`name=<确认的官网渠道名>`、`channel_type=website`、`publish_mode=auto_publish`、`base_url=<官方HTTPS站点>`、`content_rules=<CMS确认的格式约束>`、`enabled=true`、`sort_order=0`。
3. CMS 管理员先准备独立测试路径和回滚方式，并确认接收 JSON 字段：`action`、`tenant_id`、`task_id`、`channel`、`channel_type`、`title`、`body_html`、`body_markdown`、`export_format`、`content_type`、`base_url`。
4. `POST /api/v1/geo/channel-accounts`：`tenant_id=17`、真实 `channel_id`、`display_name=<可识别的官网账号名>`、`auth_type=webhook`，`credentials` 如下：

```json
{
  "webhook_url": "https://<CMS公开域名>/<专用路径>",
  "method": "POST",
  "headers": {"Authorization": "<由CMS管理员安全提供，若需要>"},
  "secret": "<可选HMAC secret，经密码管理渠道提供>"
}
```

Webhook 必须为公网 HTTPS；方法仅支持 POST/PUT/PATCH；不得使用 localhost、内网、保留地址或依赖跳转。若使用 `secret`，CMS 必须校验 `X-GEO-Signature: sha256=<hmac>`。CMS 成功响应须为 2xx；若希望系统自动取得公开 URL，JSON 返回 `url`、`published_url`、`permalink` 或 `html_url` 之一。

5. 保存后可由管理员调用 `POST /api/v1/geo/channel-accounts/{account_id}/verify-social?tenant_id=17` 做配置级校验。该结果不等于实际发布成功，也不代替 CMS 侧验签和回滚演练。

停止条件：凭证出现在读取响应或日志；URL 非公网 HTTPS；账号/渠道 tenant 不为 17；官网渠道不是 `auto_publish`；CMS 不能返回稳定公开 URL；CMS 没有删除/撤回方案。

## 6. 首单执行链与逐步停止条件

以下步骤只在第 2 节全部通过后由已授权真人执行，一次只处理 tenant 17 的一个新任务：

| 步骤 | 页面 / API | 继续条件 | 停止条件 |
| --- | --- | --- | --- |
| 1. 建任务 | `/geo/tasks`；`POST /api/v1/geo/content-tasks` | `tenant_id=17`，真实 prompt，`target_channels=["website"]` | 返回对象 tenant 非 17；误含其他渠道 |
| 2. 绑事实 | `PUT .../{task_id}/facts` | 至少三条 tenant 17、active、verified 事实 | 任一事实待核验、过期或跨业务 |
| 3. 生成母稿 | `POST .../{task_id}/generate` | 仅真人明确启动；结果未越过事实与 banned_claims | 生成调用失败、出现无依据数字/案例/承诺 |
| 4. 检查与渠道稿 | `POST .../{task_id}/check`；`POST .../{task_id}/variants` | website 稿绑定当前母稿，规则通过 | `needs_fix`、版本不一致或引用不足 |
| 5. 独立提交审核 | `POST .../{task_id}/submit-review` | 保存 `submitted` 事件，actor/role/tenant 17/article/time 完整 | 仍是旧状态；缺事件；母稿已变化 |
| 6. 独立审核决定 | `POST .../{task_id}/review` | 同一账号可执行，但必须是第二次独立请求；携带当前 `expected_article_id` 和 `expected_updated_at` | 无 pending 提交；返回 409；审核回执不匹配当前母稿 |
| 7. 导出 website 稿 | `POST .../{task_id}/export` | 审核回执完整，导出 revision 与当前稿一致 | 旧审核/旧渠道稿被当成可发布 |
| 8. 单渠道发布 | `POST .../{task_id}/push` | 只选 website + 已配置 account；一次调用 | 任何预检失败、远端非 2xx、响应无可确认结果 |
| 9. 公开核验 | 浏览器打开返回的正式公开 URL；必要时由获批人员执行 publication monitor check | 页面公开可访问，标题/正文/品牌/链接与审核稿一致 | 登录墙、404、内容漂移、非官网域名 |
| 10. 证据回填 | 任务 publication / monitor 只使用真实 URL 与实际检查时间 | 记录指向当前 task/article/channel，来源为真实公开页面 | 不得用数据库记录、Webhook 2xx 或后台状态冒充公开证据 |

同一真人操作和审核是允许的，但第 5、6 步不能合并，也不能预先写 approved。任何母稿修改都会使已有审核依据失效，必须重新走提交与审核。

## 7. PR #575 只读状态与上线顺序

截至 2026-09-13 的只读核对：PR #575 为 Draft、open，head `c90f4e3ccc89c97d31ff626bb501eb7f466ba264`，base 为 `codex/production-geo` `a344f2e921362c71b819ab00812e2e20c83bd123`，GitHub `mergeable=true`、`mergeable_state=clean`，当前检查全绿。

在数据库 0099 已由数据库协调人确认后：

1. 复核 #575 head 未变化且 CI 仍全绿；
2. 将 Draft 转 Ready，完成 GEO 范围审查；
3. 合并到 `codex/production-geo`；
4. 按 GEO 独立发布流程部署后端和对应前端；
5. 只读核对 `/health/geo`、部署 SHA、`GET /api/v1/auth/me` 及 tenant 17 空白首单状态；
6. 再由管理员按第 3–5 节配置，最后由真人按第 6 节执行首单。

不得把 #574 已合并、#575 CI 全绿或数据库中的 `review_status` 单独当成 0099 已执行或人审证据。

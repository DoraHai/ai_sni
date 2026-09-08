# 老虎 GEO 生产基础建档执行计划（仅计划，未执行）

## 1. 目标和授权边界

本计划把已经合并到 `main` 的 Tiger safe-foundation 契约转换成一次可审计的生产建档步骤。本文不授权执行，也不包含登录、令牌、部署或数据库直连操作。

固定对象：

- 客户：`tenant_id=4`，`SZ-老虎新材料`；
- 官网：`https://www.tiger-coatings.cn/`；
- 允许新建：1 个业务画像、3 个手工问题、1 个禁用的官网人工渠道；
- 不建优化单元，不启动采集、生成或发布。

执行人只能使用绑定 `tenant_id=4` 且拥有 `geo.content=edit` 的普通账号。不得使用未绑定租户的超级管理员或管理员 API Key代替客户范围校验。所有请求固定发往生产 GEO API 的 `/api/v1/geo` 前缀。

## 2. 固定载荷

### 2.1 业务画像

`POST /api/v1/geo/optimization-businesses`

```json
{
  "tenant_id": 4,
  "name": "粉末涂料与表面技术",
  "description": "TIGER/老虎的粉末涂料与表面技术业务画像",
  "sort_order": 0,
  "profile": {
    "product_name": "TIGER/老虎",
    "website": "https://www.tiger-coatings.cn/",
    "summary": "TIGER/老虎粉末涂料与表面技术",
    "industry": "粉末涂料与表面技术"
  }
}
```

接口会规范化画像。验收时上述 4 个字段必须保持一致；`honors`、`qualifications`、`capabilities`、`scenarios`、`competitors`、`recommend_reasons`、`banned_claims` 应为空数组，`audience`、`geo_scope`、`cta` 应为空字符串。不得在本轮补写未经客户确认的能力、资质、案例、竞品或承诺。

### 2.2 三个手工问题

每个问题分别调用一次 `POST /api/v1/geo/prompts`，不得使用导入、扩展或批量提升接口。

```json
{
  "tenant_id": 4,
  "question": "在建筑幕墙和系统门窗中选择粉末涂料时，最关键的性能指标和验收标准有哪些？",
  "priority": 0,
  "tags": ["cockpit-foundation"],
  "source": "manual",
  "language": "zh-CN",
  "market": "cn",
  "is_brand_probe": false,
  "unit_id": null
}
```

```json
{
  "tenant_id": 4,
  "question": "粉末涂料与常见液体涂料相比，在成本、寿命、施工和环保方面有什么差异？",
  "priority": 0,
  "tags": ["cockpit-foundation"],
  "source": "manual",
  "language": "zh-CN",
  "market": "cn",
  "is_brand_probe": false,
  "unit_id": null
}
```

```json
{
  "tenant_id": 4,
  "question": "汽车轮毂、家具家电或机器设备出现涂层失效时，常见原因、排查步骤和选型建议是什么？",
  "priority": 0,
  "tags": ["cockpit-foundation"],
  "source": "manual",
  "language": "zh-CN",
  "market": "cn",
  "is_brand_probe": false,
  "unit_id": null
}
```

### 2.3 官网人工渠道

`POST /api/v1/geo/publishing-channels`

```json
{
  "tenant_id": 4,
  "name": "TIGER 官方网站",
  "channel_type": "website",
  "publish_mode": "manual_only",
  "base_url": "https://www.tiger-coatings.cn/",
  "content_rules": null,
  "enabled": false,
  "sort_order": 0
}
```

`manual_only` 与 `enabled=false` 是本轮红线。不得把它改成 `auto_publish`、`draft_then_manual` 或启用状态。

## 3. 执行前门禁

任一门禁不满足即停止，不能通过临时扩权、改配置或换超管绕过。

1. 发布负责人回传当前 GEO 生产 SHA、发布时间与 `/geo-health` 结果。生产代码必须包含本计划引用的正式路由、`geo_read_session` 只读渠道列表以及合并契约 `main@107ea37d` 的等价内容；无法确认版本时停止。
2. `GET /api/v1/auth/me`：必须返回真实 `user` envelope；`user.id` 为普通账号整数，`user.tenant_id=4`，`user.permissions["geo.content"]="edit"`。
3. `GET /api/v1/auth/modules`：租户 4 的 GEO 必须 `available=true`，且未过期。
4. `GET /api/v1/geo/tenants`：返回范围必须包含且只能授权执行人可访问的客户；其中必须能确认 `tenant_id=4`。若身份可查看其它租户，停止并换成最小权限账号。
5. 建立唯一执行编号和 10 分钟独占变更窗口。窗口内只有一名执行人可以为租户 4 新建 GEO 基础对象。无法保证单执行人时停止，因为问题表没有数据库唯一约束。
6. 保存执行前脱敏证据。请求和响应记录不得包含 `Authorization`、Cookie、密码、API Key 或整份服务器环境。

## 4. 执行前重复检查和基线

### 4.1 业务画像重复检查

调用 `GET /api/v1/geo/optimization-businesses?tenant_id=4&status=`。空 `status` 用于同时查看 active 与 archived，避免 archived 同名记录触发数据库唯一约束。

- 名称完全等于 `粉末涂料与表面技术` 的记录为 0：允许进入创建步骤；
- 恰好 1 条且固定字段与 2.1 完全一致：记为“已存在并复用”，不得 POST；
- 恰好 1 条但字段不同，或多于 1 条：停止，回传差异，不 PATCH。

### 4.2 问题重复检查

调用 `GET /api/v1/geo/prompts?tenant_id=4&status=`，把服务端返回的 `question` 两端去空格后，与三个固定问句逐字比较。

对每个问句分别判断：

- 0 条：允许后续单独创建；
- 恰好 1 条且 `source=manual`、`language=zh-CN`、`market=cn`、`is_brand_probe=false`、`unit_id=null`、标签包含 `cockpit-foundation`：复用；
- 字段不一致或同一问句多于 1 条：停止，不能再创建或自动合并。

问题接口没有唯一约束，所以“先查再建”不是并发数据库锁。执行期间必须保持单执行人；POST 超时或连接中断时严禁直接重试，先重新 GET 并按精确问句确认结果。

### 4.3 渠道重复检查

调用 `GET /api/v1/geo/publishing-channels?tenant_id=4&enabled_only=false`。该接口会同时返回持久化记录和只存在于响应中的默认候选。

- 重复判断只统计 `id` 为正整数且 `virtual_default=false` 的持久化记录；
- 名称完全等于 `TIGER 官方网站` 的持久化记录为 0：允许创建；
- 恰好 1 条且 2.3 的全部字段一致：复用；
- 同名字段不一致或多于 1 条：停止，不 PATCH；
- `id=null` 或 `virtual_default=true` 的“官网内容中心”等默认候选不是已建档证据，也不能当成待修改对象。

### 4.4 禁止对象基线

在首个 POST 前保存以下安全 GET 的总数和持久化 ID。执行后使用同一请求复核：

- `GET /api/v1/geo/optimization-units?tenant_id=4&status=`；
- `GET /api/v1/geo/tracking-engines?tenant_id=4`，只统计正整数 ID，忽略虚拟默认项；
- `GET /api/v1/geo/channel-accounts?tenant_id=4`；
- `GET /api/v1/geo/media-placements?tenant_id=4&seed_defaults=false`；
- `GET /api/v1/geo/content-tasks?tenant_id=4&include_archived=true&limit=200&offset=0`，保存 `total`；若 `total>200`，停止并先设计完整分页取证。

不要调用 settings GET、巡检 run 详情 GET 或异步 job GET 作为基线；已有部分旧 GET 可能初始化配置或更新超时状态，不能把它们当成无副作用查询。

## 5. 正式执行顺序

每一步都采用“即时重复检查 → 最多一次 POST → 立即 GET 复核”。只有上一步完成或确认可复用，才能进入下一步。

1. **业务画像**：重新执行 4.1。仍为 0 条时，按 2.1 POST 一次。要求 HTTP 200、响应 `id` 为正整数、`tenant_id=4`、`status=active`、`unit_count=0`。随后用 4.1 的 GET 精确确认并记录 ID。
2. **问题 1**：重新拉取完整问题列表。仍为 0 条时，按 2.2 第一个载荷 POST 一次。要求 HTTP 200、正整数 ID、`tenant_id=4`、`status=active` 和固定字段一致。重新 GET 确认恰好一条。
3. **问题 2**：重复同样流程。
4. **问题 3**：重复同样流程。
5. **官网渠道**：最后重新执行 4.3。仍为 0 条时，按 2.3 POST 一次。要求 HTTP 200、正整数 ID、`tenant_id=4`、`virtual_default=false`、`publish_mode=manual_only`、`enabled=false`。重新 GET 确认恰好一条持久化记录。
6. **结束复核**：重复 4.1 至 4.4 的全部安全 GET。不得为了“验证配置”调用任何测试、采集、生成或发布接口。

若某对象已经完全一致地存在，执行记录必须写 `reused` 和原 ID；不能为了得到“本轮新建”效果再次 POST。

## 6. 幂等与不确定响应

这三个正式创建接口都没有请求级 idempotency key。执行端不得伪造“接口幂等”。本计划只采用以下受控策略：

- 业务画像与渠道由数据库唯一约束提供最终并发保护；收到 409 时停止并重新 GET，不把 409 当成成功；
- 问题没有唯一约束，依赖单执行人窗口、逐条即时查重和一次 POST；
- POST 收到超时、502、连接断开或未知状态时，立即冻结后续 POST，用 GET 查找固定对象；
- 查到恰好 1 条完全一致记录，标为 `created_outcome_recovered`；查到 0 条或多条都停止，未经代码审查和服务器日志确认不得重试；
- 任何自动重试中间件必须在执行前关闭。每个创建请求的客户端重试次数必须为 0。

## 7. 明确禁止的请求

执行记录中除第 5 节允许的 5 个 POST 外，不能出现其它非 GET 请求。特别禁止：

- `POST/PATCH /api/v1/geo/optimization-units...`；
- `PUT /api/v1/geo/tracking-engines`；
- `PUT /api/v1/geo/visibility-patrol/settings`；
- `PUT /api/v1/geo/ai-settings`、`POST /api/v1/geo/ai-settings/test`；
- `PUT /api/v1/geo/channel-polish-prompts`；
- `POST/DELETE /api/v1/geo/visibility-patrol/runs...`；
- `POST/PATCH/DELETE /api/v1/geo/content-tasks...`，包括诊断转任务、绑定事实、检查、AI 审校、生成；
- `POST/PATCH/DELETE /api/v1/geo/channel-accounts...`，包括凭证验证；
- `POST/PATCH /api/v1/geo/content-tasks/{id}/variants...`；
- `POST /api/v1/geo/content-tasks/{id}/publications`、push、push-batch；
- 任何 answer snapshot、fact、media placement、optimization period、async job 或设置类写请求。

禁止直接连生产数据库，禁止使用浏览器页面按钮代替受控请求，禁止触发默认初始化、采集、生成、发布、账号验证或部署。

## 8. 成功标准

全部条件同时满足才可报告成功：

1. 业务画像精确 1 条，固定字段正确，`status=active`、`unit_count=0`；
2. 三个固定问句各精确 1 条，均为 manual/zh-CN/cn、非品牌点名、`unit_id=null`；
3. `TIGER 官方网站` 持久化渠道精确 1 条，website/manual_only/disabled，官网地址正确；
4. 禁止对象基线的总数和持久化 ID 与执行前完全一致；
5. 请求账本只有允许的 GET 和最多 5 个已列明 POST，没有其它非 GET；
6. 没有采集 run、回答、内容任务、异步 job、渠道账号、渠道稿或发布记录因本轮产生；
7. 所有对象均可归因到明确响应 ID；空列表或虚拟默认项不能写成“已创建”。

任一条件不满足，结果只能是“停止/部分完成”，不能写“成功”。

## 9. 停止条件与补偿回滚

立即停止条件包括：身份或模块门禁失败、部署版本不明、重复记录、现存对象字段冲突、非预期对象数量变化、任何非 GET/允许 POST 请求、HTTP 401/403/409/422/5xx、响应租户不是 4、响应无正整数 ID、POST 结果不确定，以及渠道不是 manual_only+disabled。

停止后不要自动回滚。先回传完整脱敏证据，由工作台统筹和 GEO 负责人共同决定是否执行补偿。补偿只处理“本执行编号明确新建”的 ID，按逆序进行：

1. 官网渠道默认保持 `enabled=false` 即已处于安全状态。若必须恢复到完全无记录，需另行明确批准后，先确认该渠道账号数为 0，再调用 `DELETE /api/v1/geo/publishing-channels/{channel_id}?tenant_id=4&hard=true`；不得删除复用对象。
2. 对本轮新建问题逐个调用 `PATCH /api/v1/geo/prompts/{prompt_id}?tenant_id=4`，请求体 `{"status":"archived"}`。问题没有正式硬删除接口，补偿后保留审计记录。
3. 对本轮新建业务调用 `PATCH /api/v1/geo/optimization-businesses/{business_id}?tenant_id=4`，请求体 `{"status":"archived"}`。不得归档执行前已有或复用的业务。

补偿不是原事务回滚，不能把“已归档”描述为“从未写入”。补偿也属于新的生产写操作，必须取得单独批准并生成第二份请求账本。

## 10. 必须回传的证据

执行人须一次性回传以下脱敏材料：

- 执行编号、执行人 user ID、`tenant_id=4`、权限键、开始/结束 UTC 与 Asia/Shanghai 时间；
- GEO 生产 SHA、发布时间和健康检查结果；
- 执行前与执行后每个安全 GET 的状态码、响应摘要、对象总数、持久化 ID 列表和响应 SHA-256；
- 每个目标对象的决策：`created`、`reused`、`created_outcome_recovered` 或 `stopped`；
- 每个允许 POST 的方法、路径、查询参数、请求体 SHA-256、HTTP 状态、服务端 request ID 和返回对象 ID；
- 业务画像 4 个非空字段及其余空字段摘要、三个问题的固定字段、渠道的 type/mode/enabled/base URL；
- 禁止对象前后差异结果，以及“其它非 GET 请求数 = 0”；
- 所有异常原文、停止点、是否存在部分完成、是否建议补偿。

证据中不得出现 Authorization、Cookie、密码、令牌、API Key、数据库连接串、渠道凭证或完整服务器环境。无法提供请求账本或前后基线时，本次建档不得验收。

## 11. 当前状态

本文只是一份执行计划。创建、补偿、登录、数据库操作和部署均未执行。正式执行必须在独立代码审查通过后，由获准人员针对具体生产 SHA 和普通租户账号再次确认窗口。

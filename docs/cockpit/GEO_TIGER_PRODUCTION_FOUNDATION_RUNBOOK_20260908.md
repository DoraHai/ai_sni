# 老虎 GEO 生产基础建档执行计划（仅计划，未执行）

## 1. 目标和授权边界

本计划把已经合并到 `main` 的 Tiger safe-foundation 契约转换成一次可审计的生产建档步骤。本文不授权执行，也不包含登录、令牌、部署或数据库直连操作。

固定对象：

- 客户：`tenant_id=4`，`SZ-老虎新材料`；
- 官网：`https://www.tiger-coatings.cn/`；
- 允许通过一次服务端原子建档请求新建：1 个业务画像、3 个手工问题、1 个禁用的官网人工渠道；
- 不建优化单元，不启动采集、生成或发布。

执行人只能使用绑定 `tenant_id=4` 且拥有 `geo.content=edit` 的普通账号。不得使用未绑定租户的超级管理员或管理员 API Key代替客户范围校验。所有请求固定发往生产 GEO API 的 `/api/v1/geo` 前缀。

## 2. 固定载荷

### 2.1 业务画像子对象

以下对象只能作为第 5 节原子请求的 `business` 字段，不再单独调用业务创建接口。

```json
{
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

### 2.2 三个手工问题子对象

三个对象只能作为第 5 节原子请求的 `prompts` 数组，不再逐条调用问题创建接口。

```json
{
  "question": "在建筑幕墙和系统门窗中选择粉末涂料时，最关键的性能指标和验收标准有哪些？",
  "priority": 0,
  "tags": ["cockpit-foundation"],
  "source": "manual",
  "language": "zh-CN",
  "market": "cn",
  "is_brand_probe": false
}
```

```json
{
  "question": "粉末涂料与常见液体涂料相比，在成本、寿命、施工和环保方面有什么差异？",
  "priority": 0,
  "tags": ["cockpit-foundation"],
  "source": "manual",
  "language": "zh-CN",
  "market": "cn",
  "is_brand_probe": false
}
```

```json
{
  "question": "汽车轮毂、家具家电或机器设备出现涂层失效时，常见原因、排查步骤和选型建议是什么？",
  "priority": 0,
  "tags": ["cockpit-foundation"],
  "source": "manual",
  "language": "zh-CN",
  "market": "cn",
  "is_brand_probe": false
}
```

### 2.3 官网人工渠道子对象

以下对象只能作为第 5 节原子请求的 `channel` 字段，不再单独调用渠道创建接口。

```json
{
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

1. 发布负责人回传当前 GEO 生产 SHA、发布时间，并调用正式健康接口 `GET /health/geo`。必须为 HTTP 200，响应必须是 JSON 对象且同时满足 `service="geo-api"`、`db="ok"`、`geo_scheduler="running"`；字段缺失、值不符或非 200 均停止。生产代码还必须包含本计划引用的正式路由、`geo_read_session` 只读渠道列表以及合并契约 `main@107ea37d` 的等价内容；无法确认版本时停止。
2. `GET /api/v1/auth/me`：必须返回真实 `user` envelope；`user.id` 为普通账号整数，`user.tenant_id=4`，`user.permissions["geo.content"]="edit"`。
3. `GET /api/v1/auth/modules`：租户 4 的 GEO 必须 `available=true`，且未过期。
4. `GET /api/v1/geo/tenants`：返回范围必须包含且只能授权执行人可访问的客户；其中必须能确认 `tenant_id=4`。若身份可查看其它租户，停止并换成最小权限账号。
5. 建立唯一执行编号和 10 分钟独占变更窗口。窗口内只有一名执行人可以为租户 4 新建 GEO 基础对象。无法保证单执行人时停止，因为问题表没有数据库唯一约束。
6. 保存执行前脱敏证据。请求和响应记录不得包含 `Authorization`、Cookie、密码、API Key 或整份服务器环境。
7. 生产 OpenAPI 必须同时挂载 `GET /api/v1/geo/integration/read/scheduler-eligibility` 与 `POST /api/v1/geo/integration/scheduler-safe-foundation`。GET 必须返回 HTTP 200、`tenant_id=4`、`read_only=true`、`scheduler_eligible=false`、`selection_stage="enabled_settings_scan"` 和带 `Z` 后缀的 `observed_at`。接口缺失、非 200、字段缺失或 eligibility 为 true 时停止。
8. 必须核验当前部署实现了三方共享的租户行锁：scheduler 创建 run 的决策、patrol settings 更新、原子建档都先锁定同一 `tenants.id=4`。scheduler 取得锁后必须重读 settings；不存在或 `enabled=false` 必须直接跳过且不创建 run。无法核对 exact SHA 和相关并发测试时停止。

## 4. 执行前重复检查和基线

### 4.1 业务画像重复检查

调用 `GET /api/v1/geo/optimization-businesses?tenant_id=4&status=`。空 `status` 用于同时查看 active 与 archived，避免 archived 同名记录触发数据库唯一约束。

- 名称完全等于 `粉末涂料与表面技术` 的记录为 0：允许且必须进入第 5 节的唯一原子 POST，由服务端创建；
- 恰好 1 条且固定字段与 2.1 完全一致：不得单独调用业务 POST；允许且必须进入第 5 节的唯一原子 POST，由服务端复用一致业务并补齐其余对象；
- 恰好 1 条但字段不同，或多于 1 条：停止，回传差异，不 PATCH。

### 4.2 问题重复检查

调用 `GET /api/v1/geo/prompts?tenant_id=4&status=`，把服务端返回的 `question` 两端去空格后，与三个固定问句逐字比较。

对每个问句分别判断：

- 0 条：允许且必须进入第 5 节的唯一原子 POST，由原子请求创建；
- 恰好 1 条且 `source=manual`、`language=zh-CN`、`market=cn`、`is_brand_probe=false`、`unit_id=null`、标签包含 `cockpit-foundation`：不得单独调用问题 POST；允许且必须进入同一原子 POST，由服务端复用；
- 字段不一致或同一问句多于 1 条：停止，不能再创建或自动合并。

问题接口没有唯一约束，所以“先查再建”不是并发数据库锁。重复检查只是执行前证据，不允许单独创建问题；三个问题只能由第 5 节的唯一原子 POST 创建或复用。执行期间必须保持单执行人；POST 超时或连接中断时严禁直接重试，先重新 GET 并按精确问句确认结果。

### 4.3 渠道重复检查

调用 `GET /api/v1/geo/publishing-channels?tenant_id=4&enabled_only=false`。该接口会同时返回持久化记录和只存在于响应中的默认候选。

- 重复判断只统计 `id` 为正整数且 `virtual_default=false` 的持久化记录；
- 名称完全等于 `TIGER 官方网站` 的持久化记录为 0：允许且必须进入第 5 节的唯一原子 POST，由服务端创建；
- 恰好 1 条且 2.3 的全部字段一致：不得单独调用渠道 POST；允许且必须进入同一原子 POST，由服务端复用；
- 同名字段不一致或多于 1 条：停止，不 PATCH；
- `id=null` 或 `virtual_default=true` 的“官网内容中心”等默认候选不是已建档证据，也不能当成待修改对象。

### 4.4 禁止对象基线

在首个 POST 前保存以下安全 GET 的总数和持久化 ID。执行后使用同一请求复核：

- `GET /api/v1/geo/optimization-units?tenant_id=4&status=`；
- `GET /api/v1/geo/tracking-engines?tenant_id=4`，只统计正整数 ID，忽略虚拟默认项；
- `GET /api/v1/geo/channel-accounts?tenant_id=4`；
- `GET /api/v1/geo/media-placements?tenant_id=4&seed_defaults=false`；
- `GET /api/v1/geo/content-tasks?tenant_id=4&include_archived=true&limit=200&offset=0`，保存 `total`；若 `total>200`，停止并先设计完整分页取证。

另外必须使用下列 **`/integration/read` 严格只读接口**，取得巡检、回答和异步任务的完整前置水位。生产 OpenAPI 中缺少其中任何一个接口，或任何请求无法完成全量分页，均在首个 POST 前停止：

- `GET /api/v1/geo/integration/read/patrol-runs?tenant_id=4&limit=50`；后续页只使用响应的 `next_before_id` 作为同一路径的 `before_id`，直到 `next_before_id=null`；
- `GET /api/v1/geo/integration/read/answers?tenant_id=4&limit=200`；后续页原样使用响应的 opaque `pagination.next_cursor`，直到 `pagination.has_more=false` 且 `next_cursor=null`；所有页的 `pagination.watermark_max_id` 必须与首屏一致；
- `GET /api/v1/geo/integration/read/async-jobs?tenant_id=4&limit=50`；按巡检列表相同方式使用 `next_before_id` 翻到末页。

巡检和异步任务列表没有服务端 watermark 字段，客户端必须把首屏最大的 `ref.id` 固定为本次读取水位（空列表记为 0），后续页不得出现大于该水位的 ID。三个列表都要保存完整去重 ID 集合、总数、首屏水位、每页游标和响应 SHA-256；游标循环、跨页重复 ID、租户不为 4、页序异常或未到末页都属于取证失败。

这里只禁止旧的、可能在查询时协调超时状态的进度接口，例如 `GET /api/v1/geo/visibility-patrol/runs`、`GET /api/v1/geo/visibility-patrol/runs/{id}`、`GET /api/v1/geo/async-jobs` 和 `GET /api/v1/geo/async-jobs/{id}`。不得把该禁令扩展到上面的严格只读 `/integration/read` 列表。settings GET 仍不得作为基线，因为部分旧实现可能初始化配置。

### 4.5 固定执行时间窗与后置水位

完成 4.1 至 4.4 的全部前置取证后，调用 eligibility GET。把返回 false 的服务端 UTC `observed_at` 记为审计时间 `T0`。这个瞬时读取不是互斥锁，不单独作为“不会采集”的证明。

真正的保护窗口是原子建档响应中的 `protected_window.started_at/finished_at`：服务端在同一事务中取得 tenant 4 行锁，锁后重读 settings 并检查无 pending/running patrol，再一次性建立全部对象。settings 更新、手工巡检与 scheduler 决策都与该事务争用同一行锁，scheduler 得锁后还会重读 enabled，所以不能使用得锁前的旧值创建 run。

原子请求返回后立即再调用 eligibility，将 `observed_at` 记为 `T1`。必须仍为 false。`T0/T1` 只是审计边界；并发安全证据是服务端原子事务和共享行锁。原子事务结束后，系统无法阻止另一个已授权管理员日后单独启用 settings；因此未经独立审批不得执行 settings PUT，也不得宣称 eligibility 会永久保持 false。

结束复核时，对 4.4 的三个严格只读列表重新从首屏分页到底，取得后置水位和完整去重 ID 集合。比较每个列表的前后 ID 集合和数量：

- 巡检和异步任务新增 ID 必须为空；任何新增项还要记录其 `created_at` 是否落在 `[T0,T1]`，但时间不在窗口内不能推翻 ID 差异；
- 回答新增 ID 必须为空；任何新增项还要记录其 `captured_at` 是否落在 `[T0,T1]`。后置回答首屏自己的 `watermark_max_id` 固定整次后置翻页，不能复用前置 cursor；
- 前置与后置各自必须完整翻到末页。不得只查询 `captured_from=T0&captured_to=T1` 来替代完整 ID 集合比较，因为 `captured_at` 可能为空或与写入时间不同。

若任一严格只读接口非 200、返回结构不符、游标或水位不一致、分页未到底、ID 无法完整提取，执行结果必须降级为 `unverified_evidence_incomplete`。此时停止验收，不得宣称“没有新增巡检、回答或异步任务”，即使其它对象检查全部通过。

## 5. 正式执行顺序

前置 GET 和重复检查完成后，本执行单只允许一次非 GET 请求：

`POST /api/v1/geo/integration/scheduler-safe-foundation`

请求体顶层固定为 `tenant_id=4`，`business` 使用 2.1 对象，`prompts` 使用 2.2 的三个对象数组，`channel` 使用 2.3 对象。不得追加单独的业务、问题或渠道 POST。

1. 请求前最后一次执行 4.1–4.4 和 eligibility GET，记录 `T0`。
2. 原子 POST 不得自动重试。要求 HTTP 200、`tenant_id=4`、`atomic=true`、`scheduler_eligible=false`，并返回有效 `protected_window`。
3. `decisions.business`、三个 `decisions.prompts` 和 `decisions.channel` 必须都是 `created` 或 `reused`，且每个 ID 为正整数。任何 409/422/5xx 都停止，不改用旧的分步 POST。
4. 响应后立即调用 eligibility GET 记录 `T1`，要求仍为 false；再重复 4.1–4.4 的安全 GET 和严格只读分页比较。
5. 不得为了“验证配置”调用任何测试、采集、生成或发布接口。

## 6. 幂等与不确定响应

原子接口在同一租户行锁内按固定字段查重：完全一致的对象返回 `reused`，冲突、重复或 settings 启用均返回 409 并使整个事务回滚。它没有客户端 idempotency key，因此不得自动重试。

POST 超时、502 或连接断开时，先执行 4.1–4.3 GET 确认五个对象是否全部存在且字段一致，并核对服务器 request ID/事务日志。只有独立确认原事务整体回滚后才能人工重新提交；不得用旧分步接口补齐。

## 7. 明确禁止的请求

执行记录中除第 5 节允许的唯一原子 POST 外，不能出现其它非 GET 请求。特别禁止单独调用 `POST /optimization-businesses`、`POST /prompts` 或 `POST /publishing-channels`，并禁止：

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
4. 禁止对象基线的总数和持久化 ID 与执行前完全一致，三个严格只读列表均分页到底且前后完整 ID 集合和数量一致；
5. 请求账本只有允许的 GET 和最多 1 个已列明的原子 POST，没有其它非 GET；
6. 严格只读证据完整，并据此确认没有采集 run、回答或异步 job 因本轮产生；同时没有内容任务、渠道账号、渠道稿或发布记录因本轮产生；
7. 所有对象均可归因到明确响应 ID；空列表或虚拟默认项不能写成“已创建”。
8. `scheduler_eligible` 在 `T0`和 `T1` 均为 false；原子响应返回 `atomic=true`、两个服务端 UTC 保护时间和五个对象的 created/reused ID。

任一条件不满足，结果只能是“停止/部分完成”，不能写“成功”。若三个严格只读列表任一取证不完整，结果必须写 `unverified_evidence_incomplete`，且不得写“没有新增巡检、回答或异步任务”。

## 9. 停止条件与补偿回滚

立即停止条件包括：身份或模块门禁失败、健康接口非 200 或关键字段不符、部署版本不明、scheduler eligibility 接口缺失或不是 false、严格只读前置取证不完整、重复记录、现存对象字段冲突、非预期对象数量变化、任何非 GET/允许 POST 请求、HTTP 401/403/409/422/5xx、响应租户不是 4、响应无正整数 ID、POST 结果不确定，以及渠道不是 manual_only+disabled。后置严格只读取证不完整时立即停止验收并标记 `unverified_evidence_incomplete`。

停止后不要自动回滚。先回传完整脱敏证据，由工作台统筹和 GEO 负责人共同决定是否执行补偿。补偿只处理“本执行编号明确新建”的 ID，按逆序进行：

1. 官网渠道默认保持 `enabled=false` 即已处于安全状态。若必须恢复到完全无记录，需另行明确批准后，先确认该渠道账号数为 0，再调用 `DELETE /api/v1/geo/publishing-channels/{channel_id}?tenant_id=4&hard=true`；不得删除复用对象。
2. 对本轮新建问题逐个调用 `PATCH /api/v1/geo/prompts/{prompt_id}?tenant_id=4`，请求体 `{"status":"archived"}`。问题没有正式硬删除接口，补偿后保留审计记录。
3. 对本轮新建业务调用 `PATCH /api/v1/geo/optimization-businesses/{business_id}?tenant_id=4`，请求体 `{"status":"archived"}`。不得归档执行前已有或复用的业务。

补偿不是原事务回滚，不能把“已归档”描述为“从未写入”。补偿也属于新的生产写操作，必须取得单独批准并生成第二份请求账本。

## 10. 必须回传的证据

执行人须一次性回传以下脱敏材料：

- 执行编号、执行人 user ID、`tenant_id=4`、权限键、开始/结束 UTC 与 Asia/Shanghai 时间；
- GEO 生产 SHA、发布时间，以及 `GET /health/geo` 的 HTTP 状态和 `service`、`db`、`geo_scheduler` 三个字段；
- 执行前与执行后每个安全 GET 的状态码、响应摘要、对象总数、持久化 ID 列表和响应 SHA-256；
- 每个目标对象的决策：`created`、`reused`、`created_outcome_recovered` 或 `stopped`；
- 唯一原子 POST 的方法、路径、请求体 SHA-256、HTTP 状态、服务端 request ID、`protected_window` 和全部返回对象 ID；
- 业务画像 4 个非空字段及其余空字段摘要、三个问题的固定字段、渠道的 type/mode/enabled/base URL；
- `T0`、`T1`，三个严格只读列表前后各自的完整分页请求序列、固定水位、完整去重 ID 集合、数量和差异；
- eligibility 在 `T0` 及 `T1` 的 `observed_at`、`patrol_settings.exists/enabled`、`active_prompt_count` 与 `scheduler_eligible`；
- 禁止对象前后差异结果，以及“其它非 GET 请求数 = 0”；
- 所有异常原文、停止点、是否存在部分完成、是否建议补偿。

证据中不得出现 Authorization、Cookie、密码、令牌、API Key、数据库连接串、渠道凭证或完整服务器环境。无法提供请求账本或前后基线时，本次建档不得验收。

## 11. 当前状态

本文只是一份执行计划。创建、补偿、登录、数据库操作和部署均未执行。正式执行必须在独立代码审查通过后，由获准人员针对具体生产 SHA 和普通租户账号再次确认窗口。

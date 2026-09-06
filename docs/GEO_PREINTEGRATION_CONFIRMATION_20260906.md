# GEO 接入前补充确认：客户资格与纯查询

核对日期：2026-09-06。依据工作台 `COCKPIT_PREINTEGRATION_TASKS.md`，本次仅确认代码、实际部署及方案，不重述正式指标计算规则。未执行采集、生成、再次检查、配置修改、部署、迁移或生产业务数据写入。

## 1. 当前实际部署与资格检查入口

2026-09-06 15:25（Asia/Shanghai）通过 SSH 只读检查 GEO 服务主机：

- 后端、前端 RELEASE_COMMIT 均为 **d10090734e182e0a8a9e19fbbbc4db0b857ef16a**。
- release：`20260906T065319Z-d10090734e18`；geo-service active，WorkingDirectory=/opt/geo-service/current，入口 `uvicorn app.geo_main:app`，本机监听 8010。
- 线上不存在 `app/module_scope.py`；也尚无新建的 `app/geo/read_routes.py`。上一轮只读接口开发仍是本地未提交状态，不能按线上可调用接口接入。
- 已比对线上文件 SHA256 与 Git d100907 对应 blob，`app/security/auth.py`、`app/geo/tenant_scope.py`、`app/geo_main.py` 三个文件完全一致。不是只根据发布日志推测版本。

|核对项|实际代码位置|实际行为|
|---|---|---|
|GEO 开通、到期条件|`app/geo/tenant_scope.py:17–44`，geo_tenant_query|直接查询 tenant_modules：module_code=geo，status 为 active/trial，expires_at 为空或 >= date.today()。使用 SQLAlchemy table 声明，因此搜索 ORM 的 TenantModule 类名会漏掉。|
|条件的调用入口|`app/geo/routes.py:36–43`，GET `/api/v1/geo/tenants`|通过 list_geo_tenants_for_auth 过滤客户切换清单；绑定客户用户仅返回自身，不绑定客户用户返回所有有效 GEO 客户。|
|登录、用户停用|`app/security/auth.py:237–252`，require_auth|验证 JWT/到期时间，按 sub 查 User，拒绝不存在或 is_active=false 的用户。JWT 登录到期不是客户服务到期。|
|当前角色权限|`app/security/auth.py:224–234`、`:292–305`|每次请求读 Role.permissions；require_scoped_auth 按路径与方法检查 view/edit。GEO integration 路径使用 geo.content，映射在 :129–130。|
|绑定客户限制|`app/security/auth.py:87–90`、`:303–305`|ensure_tenant 拒绝绑定客户账号访问其他 tenant_id；不绑定客户的账号不被此函数限制到某一个客户。|
|GEO 业务路由装配|`app/geo/routes.py:30–34`、`app/geo_main.py:65–75`|GEO router 挂 require_scoped_auth；GEO 独立进程挂载该 router。|

**接入前缺口：客户清单过滤不等于业务接口的逐请求开通/到期校验。** 在已核对的部署版 GEO 代码中，tenant_scope 只由客户清单调用，require_scoped_auth/ensure_tenant 不读取 tenant_modules。因此不能承诺“已过期客户即使持有原来的 ID，也一定无法调用所有 GEO 数据接口”。新建本地 read_routes 复用相同身份/菜单/客户鉴权，也尚未补上这一资格门禁。

上述是 GEO 应用层的明确边界；本次未完整验证公网网关所有可能的附加策略，也没有用真实到期客户做越权访问实验，不将应用层缺口夸大为全站已被绕过。

日期边界：现有代码到期日当天有效；用服务进程的 date.today()，不是显式 Asia/Shanghai。主机 date 回显 +08:00，但本次未读取进程环境核实 TZ 覆盖，不能把主机时间回显当成所有进程日期策略已统一的证明。

### 拟定接入处理（本次不改代码）

1. AUTH-01 由认证/工作台后端明确权威资格入口，输入已认证用户与选中 tenant_id，输出每个模块的 eligibility、expires_at、permission、available、reason_codes、evaluated_at。必须区分 not_enabled、expired、permission_denied、unknown；查询失败不能默认 available=true。
2. 权威数据继续来自既有 tenant_modules 和角色权限，不新增/复制权限表。GEO 数据接口本身也需绑定资格依赖，不能只信任前端模块列表或工作台转发的布尔值。
3. 先将该依赖纳入本次新只读入口及正式指标入口，确保深链/旧 ID 同样检查；其他 GEO 业务入口统一补齐需在实施时列清单，不以客户列表替代。运维 Key 的特权政策单独明确，工作台不使用未绑定租户的超级管理员 Key 代理客户。
4. 七种非空模块组合、零模块、到期/停用、角色撤权、客户切换、直接 ID 访问与查询失败均纳入验证。共享 User/JWT/数据库实际兼容性仍归 ID-01，不能只凭模型同名确认。

接口名称由 AUTH-01 统一，本轮不宣称已有某个 `/module-scope` 上线。只开通一个或两个模块的客户不应被默认视作三个模块均可用。

## 2. 首期读取白名单与 GET 副作用

下列旧接口前缀均为 `/api/v1/geo`。这里“只读”指当前处理链不初始化业务配置、不改任务状态、不发起采集或生成；不表示已满足上面的开通/到期门禁。

|需求|现有接口|只读结论与位置|
|---|---|---|
|客户清单|GET `/tenants`|只读；routes.py:37、tenant_scope.py:47/56。只代表可用 GEO 客户清单，不是 SEM/SEO 资格接口。|
|问题清单|GET `/prompts`|只读；content/routes.py:2022。返回当前问题文本，不能冒充历史提问。|
|回答原文|GET `/answer-snapshots`|只读；content/routes.py:2553。旧返回缺完整历史供应商/模型、时间过滤、分页及准入解释，工作台应改接新聚合。|
|正式周指标及字典|GET `/integration/metrics/snapshot`、`/dictionary`|只读；integration.py:125/132。继续作为正式数据来源。|
|统一指标任务|GET `/integration/tasks`、`/tasks/{id}`|只读；integration.py:191/208。与内容任务 ID 不同。|
|内容任务摘要|GET `/content-tasks`|列表只读；详情序列化另有副作用，不能照搬。|
|条件说明|GET `/integration/tasks/{id}/retest-plan`、`/baseline-readiness`、`/execution-readiness`|读取计划/阻碍，不执行再次检查。execution-readiness 的内部矩阵是查询；不是下面会初始化的 publishing-channels/auto-push-status 路由。|

|含副作用的 GET|实际动作/位置|纯查询处理|
|---|---|---|
|`/tracking-engines`|content/routes.py:5333 调 `_ensure_default_engines`|新 capabilities 仅查询已有配置。|
|`/publishing-channels`、`/publishing-channels/auto-push-status`|content/routes.py:5522/5538 调 `_ensure_default_publishing_channels`|新 capabilities 不初始化渠道、不试连。|
|`/content-tasks/{id}`|`_task_payload(detail=True)` → `_channel_options_payload` → ensure，content/routes.py:743/870–871|新内容详情自行查询已有对象，不调用旧详情处理函数。|
|`/visibility-patrol/runs`、`/runs/{id}`|content/routes.py:4814–4846 调 reconcile_stale_patrol_run，可能更新超时状态|新 patrol-runs 仅读取 stored_status，加独立 stale 提示。|
|`/async-jobs`、`/async-jobs/{id}`|content/routes.py:4599–4641 调 reconcile_stale_job，列表还 reconcile_stale_content_tasks|新 async-jobs 不回写状态、不取得执行锁、不调恢复。|

上述是首期范围，不把未列 GET 自动纳入白名单。禁止 POST 采集、生成、评分刷新、retest 或任何真实执行动作。

## 3. 聚合接口最终本地实现约定

**已本地实现，未提交、未部署，也尚未加入上述资格门禁。** 新前缀 `/api/v1/geo/integration/read`：

- `/answers`、`/answers/{snapshot_id}`；实现 read_routes.py:81/147，序列化 read_model.py:77。
- `/period-context`；实现 read_routes.py:43、read_model.py:43。
- `/capabilities`、`/content-tasks/{content_task_id}`、`/patrol-runs[/{patrol_run_id}]`、`/async-jobs[/{async_job_id}]`。

新查询使用独立 autoflush=False session，在第一次业务查询前执行事务级 REPEATABLE READ、READ ONLY；read_routes.py:25–30。当前代码不调用旧 ensure/reconcile。必须在 PostgreSQL 环境实测强制只读和实际 SQL，再配合资格门禁验收后才能接入。

回答请求示例：

```http
GET /api/v1/geo/integration/read/answers?tenant_id=1&week_end=2026-08-31&limit=50
```

可选 prompt_id、engine_key、patrol_run_id、source_kind、captured_from、captured_to；时间带时区，区间左闭右开。limit 默认50/最大200，按 captured_at DESC、id DESC，签名 cursor 绑定租户/条件/已解析正式周/最大ID，next_cursor=null 表示末页。巡检和异步列表另用 limit、before_id/next_before_id。

回答返回字段摘要（结构详见既有 JSON 示例，非生产记录）：

```json
{
  "ref": {"module":"geo","type":"answer_snapshot","id":9010},
  "question": {"id":9071,"historical_text":"示例历史问题","current_text":"当前问题","historical_text_source":"patrol_item"},
  "engine": {"key":"deepseek","provider":"deepseek","model":"deepseek-chat","model_revision":null,"metadata_source":"patrol_item"},
  "captured_at":"2026-08-29T02:15:00Z",
  "captured_at_local":"2026-08-29T10:15:00+08:00",
  "time_basis":"stored_utc",
  "source": {"kind":"real","stored_sample_mode":"openai_compat","simulated":false,"sampling_method":"unprimed_json_v2","analysis_status":"completed","verified_server_record":true},
  "sample_eligibility": {"eligible":true,"reasons":[]},
  "week_membership": {"within_window":true,"included_in_cohort":true,"reasons":[]},
  "metric_adoption": [{"metric_key":"geo.visibility.ai_mention_count_7d","status":"unavailable","reasons":[{"code":"insufficient_samples","scope":"week","message":"合格回答少于 8 条"}]}]
}
```

这只是单条字段节选；实际列表还包含 excerpt、URL、提及/竞品、comparison_metadata、relations 等；详情增加 raw_text。外层包含 tenant_id、evaluated_at、timezone、official_week_end、observation_window、unknown_time_count、pagination、items 和 period_context_url。

- 历史 provider/model 只取关联服务端巡检单元，缺失为 null；不能用现时配置补历史。model 是请求模型别名，不冒充不可变修订号。
- 本条被排除用 status=excluded、scope=sample；本条合格但整周不足用 unavailable、scope=week；窗口外另标 scope=window。参与统计不等于回答产生了咨询。
- 真实/人工/模拟/未知仍分别展示，真实标签不能代替 verified_server_record。prefer_real 不保证禁止模拟回退。
- `/period-context` 独立提供正式周边界和缺数说明；正式数字不由分页回答汇总。本轮不重复正式规则。
- capability 的 effective_mode=null，configuration 推断和实际执行分开；不会因为存在 Key 而显示“已取得真实回答”。

完整本地交付与测试边界：`GEO_BRIEF_EVIDENCE_READ_IMPLEMENTATION_20260906.md`；示例：`GEO_READONLY_RESPONSE_EXAMPLE_20260906_45.json`。

## 4. 工时确认

**原 5–8.5 人日是粗估，不能认定已完整包含目前明确的全部纯查询改造。** 已包含基础聚合、预检及回归意图，但没有完整拆出配置初始化隔离、所有进度查询、周期上下文及对象关联。

|首期只读工作包|估算人日|
|---|---|
|后端聚合、历史元数据/分页、周期解释、配置/内容/进度纯查询、类型关联|2.5–3.5|
|工作台展示适配与调用接线|1–1.5|
|只读约束、租户隔离、契约与前端联调回归|1–1.5|
|原已细化的只读包合计|**4.5–6.5**|
|本次确认新增的资格依赖接入及拒绝路径回归（权威来源/入口确认后）|**另计 1–2**|

因此包含资格补齐后的 GEO 首期包粗估 **5.5–8.5 人日**；这是范围预算，不是“从现在起还要投入”的剩余工时，也不是已消耗工时。后端只读与前端调用适配已有本地代码，工作台最终页面接线、AUTH-01/ID-01和真实环境验收仍未完成。

该增量不包含构建跨模块认证中心、统一身份迁移或三个模块的全部授权改造；若权威服务协议/身份转发方案有变化应另估。后续真实采集此前单列2–3人日，**不计入本次只读包**；内容生成和再次检查执行亦不纳入。

当前阻碍接入的优先级是资格检查入口及拒绝路径确认，其次是新只读接口 PostgreSQL 验收与工作台联调。无需等待真实采集数据才能补资格门禁，但当前不能把未部署接口和未补齐授权视作接入已就绪。

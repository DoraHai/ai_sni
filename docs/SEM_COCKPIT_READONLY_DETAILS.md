# SEM 首期只读 B 包：接口、消费适配与本地验收

开发起点：origin/main `e9f55942307d9e09228a98274eadf51d411a0920`（PR #374），
独立分支 `codex/sem-cockpit-readonly-details`。本批只修改 SEM 读取适配及交付材料。
现有旧页面接口、鉴权实现、百度同步/写回、数据库 Schema、驾驶舱演示原型均不修改。

## 已实现范围

| GET 接口 | 数据、窗口 | 账户 | 权限及副作用 |
| --- | --- | --- | --- |
| /api/v1/dashboard/cockpit | A：保持原有报告/设备及缺报契约，不查询或返回电话按钮点击指标。必传日期，含首尾1–366天 | 全客户已存报告或指定本地账户；未归属单列，含停用账户历史 | monitor.dashboard；仅 SELECT，无百度/AI/缓存写入 |
| /api/v1/keywords/cockpit | 关键词资产分页＋同账户报告；日期成对传入，否则以所选账户范围最新报告日锚定近7天 | 资产和日报按账户＋关键词ID关联，NULL不推给已知账户 | optimize.keywords；仅 SELECT 与内存计算 |
| /api/v1/keywords/cockpit/{keyword_id} | 报告、设备、电话点击、单关键词地域及星期×小时。必传日期，1–366天 | 显式 all/single；每个维度独立列账户覆盖 | optimize.keywords；不放宽既有鉴权。新路径不继承旧详情的看板权限特例 |
| /api/v1/search-terms/cockpit | 分页搜索词及每账户实际同步窗口；拒绝日期参数 | all/single；窗口覆盖全部筛选结果，不受当前页限制 | optimize.searchterms；只读快照，不同步/加词/否词 |

所有请求必带 `tenant_id`，可带正整数 `baidu_account_id`。保留 require_scoped_auth 的客户、
模块开通与 SEM 身份校验。无登录401、权限拒绝403、账户/关键词不属于范围404、无效或未知参数422。
未知参数、重复参数均拒绝；不支持的“主题/日期联动”不能静默忽略。

关键词列表支持 q（按字面子串）、campaign_id、page/page_size（1–200）；搜索词支持
q、campaign_id、adgroup_id、page/page_size。关键词日期仅传一端返回422；默认窗口锚点不受 q/分页影响。
总条数是筛选后的资产/快照条数，不能用当前页数量代替。关键词列表不承诺枚举所有历史报告中的已删除资产。

## 字段规则

- 统一 `contract_version=sem-cockpit-v1`、`module=sem`、`read_only=true`、`is_demo=false`。
  A基础字段保持不变；电话点击只在B关键词列表/详情返回。is_demo=false只表示读取存储，不表示生产已上线。
- 金额 CNY；CTR ratio=click/impression；CPC=cost/click。除零或缺分母为null；
  搜索词重新计算，避免直接使用历史存储百分数。聚合按总量重算，不平均CTR。
- `account_scope.configured_account_ids` 是所选客户配置的账户；列表的 `observed_account_ids`
  是全筛选结果中的实际账户（可包含null），不是仅当前页。报告的 accounts 含配置账户及实际报告归属。
- 关键词资产的 `asset_updated_at` 与日报 `coverage.updated_at` 分离。
  详情的keyword_assets按账户返回已存关键词名称及资产更新时间；只有历史报告而无资产时为空，不猜测当前资产状态。
  地域和小时维度分别读取自己的 fetched_at，逐账户覆盖包含无数据账户。
- `coverage.status=observed/no_data`；missing_dates只说明无记录日，completeness持续为unknown。
  即使每天有行，也不能证明所有关键词/设备已采齐；updated_at是范围内最新采集时间，不是完整导入承诺。
- 缺日/缺格为null；有记录且数值0保留0。时段 `dimension=weekday_hour`，168格，非每日逐小时。
  地域按 region_level 分别返回 totals_by_level，不提供省＋市重复合计。
- 搜索词 windows 按账户、window_start/end分组，返回最早/最新synced_at、未知时间条数；
  mixed_windows 标记不同窗口，拒绝跨窗口总量，也不把一个账户时间复制给其他账户。
  行级NULL保留；无快照不证明没有搜索。数据库按账户替换快照，纯查询不能恢复已覆盖历史。
- 所有记录只有已存证据；不修复或回填上游已归零的花费/点击/展现。缺原始数据的完整性不提高。
- 返回读取时间 retrieved_at 与采集时间分离，统一显式UTC偏移；统计日期/周内时段沿用报告上海日期语义。

电话按钮点击字段格式（**虚构示例**）：

```json
{
  "value": null,
  "known_subtotal": 2,
  "unit": "count",
  "source_field": "ocpcConversionsDetail2",
  "status": "partial",
  "stored_rows": 2,
  "known_rows": 1,
  "unknown_rows": 1,
  "completeness": "unknown"
}
```

只读 `raw_metrics.ocpcConversionsDetail2`，不信任已归零的 conversions 列。
原始类型必须是数值/字符串，值可解析为有限非负整数且不超BigInteger正值范围；布尔、对象、数组、
空串、null、缺字段、负数、小数、NaN/Infinity均记unknown。原始字段类型在数据库侧保留，
不会因SQLite布尔转整数而误认成1；PostgreSQL使用jsonb_typeof校验类型。
数据库只提取该字段和类型并分组计数，不返回整份raw_metrics。

全部已存行有有效字段才返回value；部分行有效只返回known_subtotal，完全不可用两者均null；
有原始0保留0。此处observed也不等于完整采集。当前未开放设备/地域/小时电话点击拆分。
电话按钮点击不等于拨通电话或有效咨询；关键词报告花费不等于全广告产品消耗。

## 纯查询边界

处理位置：`app/api/keywords.py`、`app/api/search_terms.py`注册新增路径，委托
`app/sem_cockpit_details.py`；报告及电话点击共用`app/sem_cockpit_readonly.py`。
只读层不导入同步/AI/写回服务，不add/flush/commit，不创建缓存，无新Schema或SemTask依赖。

旧`/dashboard/today`仍带实时账户查询，工作台不调用它；旧keywords/search-terms保留原行为。
reports/analysis、monthly及export不在白名单，不通过force=false假装只读，也不为本包开发AI缓存读取。
新详情不附带全历史bid_trend或窗口不一致的关联搜索词；搜索词使用独立接口显示真实窗口。

## 工作台消费交付

`integrations/sem-cockpit/readonly-client.mjs` 为无框架ES模块，不改独立驾驶舱工作区。
仅支持report/keywords/keywordDetail/searchTerms四种GET资源，无默认网络实现、无Token保存、
无持久缓存、无演示回退。调用方注入经确认的用户认证transport及onClear。

- 未setContext不发送请求；context必须含tenantId/userId/authorizationRevision/allowedReads。
  这些是已确认身份服务的消费结果，不能由演示配置充当权限。服务器仍是最终权限裁决。
- context切换/撤销时中止旧请求并调用onClear。调用方需清理可见数据、搜索、对话及其派生上下文。
- 同资源新筛选取消旧请求；即使transport忽略abort，迟到结果和旧错误也归为STALE_RESPONSE，不交给视图。
- 401/403清除资格并拒绝后续读取。返回客户、账户、日期、来源、详情对象或契约不符同样拒绝。
- 搜索词不接受日期参数；report和详情日期必填。空值保持空值，不自动当0，也不自动换用演示。
- 不提供模型调用。工作台以后接AI时仍需校验授权及上下文，不把客户端allowedReads当服务端鉴权。

完整固定样例：`integrations/sem-cockpit/examples.synthetic.json`。四组均由本地合成SQL夹具及真实路由生成，
外层synthetic=true明确说明虚构；响应内is_demo=false保留真实接口形状。不是客户数据、上线证据或原型演示数据替换。
客户端测试直接消费这四组样例。详见同目录README。

## 本地验证和剩余限制

执行：

```text
python -m pytest -q tests/test_sem_cockpit_readonly.py tests/test_sem_cockpit_details.py tests/test_sem_tenant_account_identity.py tests/test_sem_identity_repair_preview.py tests/test_keyword_refresh.py
node --test integrations/sem-cockpit/readonly-client.test.mjs
git diff --check
```

测试使用合成内存SQLite，夹具建立后禁止非SELECT SQL，百度调用与AI生成被设为失败桩。
另通过专用本地PostgreSQL 16.15的原生JSONB/聚合/只读事务测试；未运行应用启动、Alembic或生产调用。
实测修复PostgreSQL SUM(bigint)返回Decimal导致CPC计算异常，A/B共用计数转换为int；A字段口径不变。
关键词刷新回归仅运行已有mock测试，不发同步请求。

已完成：账户隔离、已知电话点击小计/缺失/显式0、日期/分页、独立维度鲜度、省市不重复合计、
168格缺失/0、混合搜索词窗口、菜单/客户/模块/身份/未登录拒绝、客户端迟到响应/错误及撤权。
不声称全仓库或线上验收完成。

最终本地结果：133项Python测试通过（含1项原生PG集成矩阵）、11项Node消费测试通过，均无跳过；
仅有既有jieba/pkg_resources弃用警告。git diff --check通过。前端应用未改动，不执行前端发布构建。

仍需外部条件：实际部署版本、受控测试客户与身份、AUTH-01/ID-01的身份透传和模块资格结论。
这些条件确认前，驾驶舱原型保持演示，不直接接真实服务；线上数据数量、历史完整性仍未知。
隔离PostgreSQL环境已自行解决；当前无必须真人判断/操作的测试项，真实服务联调前置不记为已验收。
新API及消费适配代码不自动部署。发布仍须独立SEM后端生产同步，migration=not-run；
工作台页面集成由其工作区另行完成，不修改SEO/GEO/门户。

## 精确文件清单

1. app/api/keywords.py：新增两个工作台GET。
2. app/api/search_terms.py：新增窗口快照工作台GET。
3. app/sem_cockpit_readonly.py：B复用的原始电话点击字段类型/聚合及关键词过滤；A不调用电话点击查询。
4. app/sem_cockpit_details.py：关键词、详情维度及搜索词只读适配。
5. docs/SEM_COCKPIT_POSTGRES_VALIDATION.md：隔离PostgreSQL验证条件、用例及负责人事项。
6. tests/test_sem_cockpit_details.py：SQL、契约与权限测试。
7. integrations/sem-cockpit/readonly-client.mjs：消费适配。
8. integrations/sem-cockpit/readonly-client.test.mjs：客户端测试。
9. integrations/sem-cockpit/examples.synthetic.json：完整虚构响应。
10. integrations/sem-cockpit/README.md：接线说明。
11. docs/SEM_COCKPIT_READONLY_CONTRACT.md：链接后续扩展说明。
12. docs/SEM_COCKPIT_READONLY_DETAILS.md：本批契约及交付记录。
13. tests/test_sem_cockpit_postgres.py：专用本地数据库桥接及原生只读集成矩阵。

## 待发布包状态

当前HEAD仍为e9f55942307d9e09228a98274eadf51d411a0920，B改动未提交/推送/合并，
无发布进程；生产实际SHA未知。工作台负责人协调后续提交审核、main及独立SEM后端生产同步。
包范围为上述SEM文件；工作台页面/对话/跨模块状态由工作台负责人接入，不改cockpit-foundation。
依赖是既有六张报表/资产表、原鉴权、确认的用户身份透传；无新Schema或SemTask迁移。
回滚采用本次发布前核验的SEM后端不可变产物及受控流程，不能使用未经核验的历史SHA；
工作台同时停止消费未支持的B端点，避免404回退成演示。无数据库变更，无数据库回滚步骤。
发布前需记录目标SHA、回滚产物、实际schema兼容核对及专用GET验收身份；目前尚未获得这些生产证据。

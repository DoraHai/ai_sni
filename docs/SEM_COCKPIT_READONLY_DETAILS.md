# SEM 工作台只读接口：生产后端 active-account scope 同步

生产后端基线：`origin/codex/production-sem-backend@88649dd20b0fe939c153e029ec007d6bb27f0cf9`。
本次独立同步只更新四个现有 GET 路由共用的只读 reader、合成测试夹具、回归测试、
发布选择集与本说明。现有路由文件、鉴权实现、百度同步/写回、数据库 Schema、前端和驾驶舱消费文件均不修改。

## 已实现范围

| GET 接口 | 数据、窗口 | 账户 | 权限及副作用 |
| --- | --- | --- | --- |
| /api/v1/dashboard/cockpit | A：保持原有报告/设备及缺报契约，不查询或返回电话按钮点击指标。必传日期，含首尾1–366天 | 默认仅 active 账户，未归属单列；显式指定租户内非 active 账户可读历史 | monitor.dashboard；仅 SELECT，无百度/AI/缓存写入 |
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
- all 模式下 `account_scope.configured_account_ids` 只列 active 账户，
  `excluded_non_active_account_ids` 明示列出所有默认排除账户，`excluded_archived_account_ids` 保留归档子集以兼容既有消费者。
  显式指定租户内非 active 账户时仍允许只读历史，并返回 `selected_account_status`；外租户或未知账户仍返回404。列表的 `observed_account_ids`
  是全筛选结果中的实际账户（可包含null），不是仅当前页。报告的 accounts 含当前范围账户及实际报告归属。
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

## 本次生产同步边界

生产后端基线已经注册以下四个 GET 路由，本次不重写路由文件：

1. `/api/v1/dashboard/cockpit`
2. `/api/v1/keywords/cockpit`
3. `/api/v1/keywords/cockpit/{keyword_id}`
4. `/api/v1/search-terms/cockpit`

本次更新 `app/sem_cockpit_readonly.py` 与 `app/sem_cockpit_details.py`，让默认范围只包含 active 账户，
同时允许显式选择租户内非 active 账户查看历史。测试夹具和两组只读测试覆盖 active、inactive、archived、
仅 archived、未归属、跨租户、缺报、零值、电话字段、地域、星期×小时及搜索词窗口。

发布工作流保留生产后端已有的全部安全测试，只追加两个 cockpit 测试文件。它仍只允许手动输入当前
`codex/production-sem-backend` 精确 SHA，仍不运行迁移，不发布前端、SEO 或 GEO。

`tests/test_sem_cockpit_postgres.py` 已存在于生产后端基线，本次不改。它只接受专用 loopback 数据库
`sem_cockpit_ro_test`，并在只读事务中验证 JSONB 类型、聚合精度和数据库写入阻断；未配置专用地址时跳过，
不会尝试连接其它数据库。

## 变更文件

1. `app/sem_cockpit_readonly.py`
2. `app/sem_cockpit_details.py`
3. `tests/sem_cockpit_fixtures.py`
4. `tests/test_sem_cockpit_readonly.py`
5. `tests/test_sem_cockpit_details.py`
6. `.github/workflows/production-sem-backend-deploy.yml`
7. `docs/SEM_COCKPIT_READONLY_DETAILS.md`

本同步不含 integrations、frontend、平台路由、SEO/GEO、迁移、同步、投放或写回文件。
提交只进入独立 Draft PR；合并与部署需在独立审查通过后另行推进。

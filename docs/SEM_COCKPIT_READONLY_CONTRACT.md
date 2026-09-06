# SEM 获客工作台只读接入 v1

本地开发基线：2026-09-06 fetch 后的 origin/main，e05425475e3a4ec9000d64ecb10cbf5c8e3a081a。
分支 codex/sem-cockpit-readonly-adapter；尚未提交、发布或连接生产数据库。

真实原型位于另一个已有 worktree：
`D:/SNIPERS国内版/ai_sni-worktrees/cockpit-foundation/cockpit/prototype/cockpit-prototype.html`。
其 `docs/COCKPIT_DATA_CONTRACT.md` 与 `docs/cockpit/SEM_OWNER_FEEDBACK_20260906.md`
已用于核对范围。该驾驶舱原型及其业务代码本轮均未改动，仍为演示数据。

## 文件范围

| 文件 | 修改用途 |
| --- | --- |
| app/api/dashboard.py | 在既有受保护 router 下注册 GET /cockpit |
| app/sem_cockpit_readonly.py | 只查询已有账户、关键词日报；聚合、覆盖情况及契约 |
| app/api/leads.py | 同筛选列表统计；独立无个人信息的 GET /cockpit-summary |
| tests/test_sem_cockpit_readonly.py | 内存 SQL 数据夹具、HTTP 权限及只读验收 |
| docs/SEM_COCKPIT_READONLY_CONTRACT.md | 本接入契约与交付说明 |

无新 Schema、无 SemTask 依赖、无迁移命令。无百度请求、同步、AI、缓存写入、资金执行。
复用现有 router 和 require_scoped_auth；不修改鉴权、app/baidu、SEO、GEO、门户、Nginx。

## 请求及权限

登录用户使用现有 Bearer 会话，不能为工作台配置全局管理员 API key。
两端点分别返回，权限失败不能用另一端点/管理员权限补取。

| GET 路径 | 必填 | 可选 | view 权限 |
| --- | --- | --- | --- |
| /api/v1/dashboard/cockpit | tenant_id, start_date, end_date | baidu_account_id | monitor.dashboard |
| /api/v1/leads/cockpit-summary | tenant_id, start_date, end_date | status, campaign_id | verify.leads |

客户/模块/SEM 身份限制仍由原 require_scoped_auth 执行。账户 ID 为本地 ID。
日期为 YYYY-MM-DD，上海日期，首尾均包含，1–366 天，必须显式传入。
不支持或重复参数返回 422，不偷偷忽略主题、关键词、计划等筛选。
无登录 401，无权限/客户或模块隔离失败 403；账户不属于该客户或不存在为 404。
非法 status 为 400；无效日期/超长窗口为 422；基础设施失败保留失败状态，不伪造零值。

## 广告报告语义

- source=kw_report_snapshots，source_scope=keyword_report_only：仅已落库关键词报告，不能称全部百度广告产品消费。
- 未传账户表示显式契约 all，聚合该客户全部报告，包含停用账户的历史报告及未归属账户行；绝不默认首个账户。
  传账户则仅过滤该本地账户。accounts 提供各账户独立统计、缺报日及更新时间。
  NULL 账户单列，status=unassigned；不得把它推给某个当前生效账户。
- cost 为 CNY，click/impression 为次数；ctr=click/impression（小数比例），cpc=cost/click。
  比率按总量重算，不平均各账户 CTR。零分母返回 null。币种采用现有 SEM 人民币金额口径，不支持跨币种混算。
- metrics 是选定区间内已有记录的求和，含缺报时仍是已观测小计，必须与 coverage 一起呈现。
  完全无行时指标全部 null；trend 中缺日 null，确有零值记录的日期为 0。
- coverage.status=observed/no_data；completeness 永远 unknown。observed_days、missing_dates
  仅证明日期上有无记录，不能证明所有关键词、设备、账户都采集齐全。不得显示“完整数据”。
- coverage.latest_report_date 为当前筛选内最新报告日；updated_at 为当前筛选内最大 fetched_at，
  依照已有同步存储的 UTC 加上时区。accounts 分别返回该证据；不能把某账户新时间用作其他账户时间。
  retrieved_at 是接口读取时间，不能标成同步时间或“实时”。
- 上游花费/点击/展现缺字段也可能曾被归零。本层不重建已丢失的事实，observed 不保证原始字段齐全。
- devices 只输出观察到的设备值，0=PC，1=移动，其他值/空值标未知，不推算缺失设备。
- 历史 conversions 有缺字段转零，因此 phone_button_clicks 在 unavailable 中说明不可用。
  原型泛称“转化”不得映射为有效咨询。余额/账户日预算不在本接口中读取。

## 线索台账语义与兼容修改

- source=leads；日期按 lead_time，未填日期不落入范围；状态是当前状态，不能回放过去某日状态。
- received_leads 为所选筛选下已有台账记录数；new/following/won/invalid 分别计数。
  not_invalid 包含 new，不能称“已确认有效”；valid_consultations 为 null。
- 没有可靠账户外键，不通过计划名、关键词文本或当前账户反推历史归属。
  传 baidu_account_id 返回 422。驾驶舱选账户时应将线索区显示为“不支持账户筛选”，不能混用客户总量。
- 无 source 同步完成证据，completeness=unknown，updated_at=null；零条台账不等于零咨询。
- deal_amount 只统计 won；若任何成交记录金额缺失，工作台金额返回 null，
  deal_amount_coverage 显示成交条数/有金额条数。无成交记录时账本成交金额为 0。
- 返回字段无姓名、电话、备注、外部 ID、关键词或其他个人信息。工作台/智能体只消费此汇总，
  不直接把已有 GET /leads 的原始列表送入大模型。
- 已有 GET /leads 的 summary 改为与列表相同客户/日期/状态/计划筛选，仍不受分页影响，
  新增 summary_scope=filtered。旧字段保留；win_rate 仍为百分数且零分母仍为 0 以兼容旧页面，
  新增分母说明 not_invalid_in_filtered_scope。工作台汇总不输出该易误读的成交率。
  这会改变旧统计卡在筛选后的数字，属于有意修复，后续发布需验收既有线索页面。

## 请求和返回示例（全部虚构，仅展示节选）

```http
GET /api/v1/dashboard/cockpit?tenant_id=1&start_date=2026-09-01&end_date=2026-09-03&baidu_account_id=11
Authorization: Bearer <用户会话>
```

```json
{
  "contract_version": "sem-cockpit-v1",
  "tenant_id": 1,
  "module": "sem",
  "is_demo": false,
  "read_only": true,
  "source": "kw_report_snapshots",
  "source_scope": "keyword_report_only",
  "window": {"start": "2026-09-01", "end": "2026-09-03", "timezone": "Asia/Shanghai", "inclusive": true},
  "account_scope": {"mode": "single", "baidu_account_id": 11, "includes_unassigned": false},
  "metrics": {"cost": 10.0, "click": 2, "impression": 100, "ctr": 0.02, "cpc": 5.0},
  "coverage": {"status": "observed", "completeness": "unknown", "observed_days": 2, "missing_dates": ["2026-09-02"], "latest_report_date": "2026-09-03", "updated_at": "2026-09-04T01:00:00+00:00"}
}
```

`is_demo=false` 是接口契约值，表示实际读取存储，不证明本示例为真实客户数据。
完整响应还含 units、retrieved_at、accounts、trend、devices、unavailable。

```http
GET /api/v1/leads/cockpit-summary?tenant_id=1&start_date=2026-09-01&end_date=2026-09-03
Authorization: Bearer <用户会话>
```

```json
{
  "source": "leads",
  "filters": {"status": null, "campaign_id": null, "account_scope": "tenant_only"},
  "updated_at": null,
  "completeness": "unknown",
  "metrics": {"received_leads": 4, "new": 1, "following": 1, "won": 1, "invalid": 1, "not_invalid": 3, "deal_amount": 100.0, "valid_consultations": null},
  "deal_amount_coverage": {"won": 1, "with_amount": 1}
}
```

## 既有能力与暂不支持

关键词列表仍复用 GET /keywords（optimize.keywords），固定最新报告锚定近 7 日，
不接收工作台任意日期。关键词详情最多 366 日，其地域是单关键词，schedule_analysis 为星期×小时，
非每日逐小时，维度鲜度不能从主报告外推。此轮未增加客户级地域/时段/关键词日期列表。

搜索词 GET /search-terms（optimize.searchterms）仍是同步窗口，不能支持历史趋势；
window 不保证跨账户一致。禁止把工作台全局日期看作上述接口已生效。
本轮不把这些列表纳入新聚合，不触发可能写缓存的详情分析。预算、任务、审批/执行队列整合后置。
无跨主题配置、点击到成交精确归因、CRM、百度转化回传、自动核实咨询。

## 验收与交付状态

- [x] 独立分支/worktree，原仓库冲突及旧迁移 worktree 原样保留。
- [x] 缺报 null 与已有零值区分；CTR 同分母重算；账户明示且逐账户日期覆盖。
- [x] 线索列表/总数/汇总筛选一致，分页不改变汇总；新接口无个人信息。
- [x] 未登录、菜单、客户、模块、身份门禁测试；外客户账户拒绝；不支持筛选拒绝。
- [x] 内存 SQL 查询测试在夹具建立后拒绝所有非 SELECT SQL，无生产数据库连接。
- [ ] 驾驶舱代码接线与逐屏验收（归属另工作区，未修改）。
- [ ] 已授权测试客户的实际 API 联调、PostgreSQL 实例验证及数据完整性核验。
- [ ] 线上部署 SHA、运行数据及迁移状态验证；当前未知。

本地运行：`python -m pytest -q tests/test_sem_cockpit_readonly.py tests/test_sem_tenant_account_identity.py tests/test_sem_identity_repair_preview.py`。
最终结果：76 passed，0 skipped；1 条既有 jieba/pkg_resources 弃用警告。新增测试 26 项，
账户身份回归 50 项。`git diff --check` 通过。复审追加了未知/重复筛选拒绝和成交金额缺失返回 null，均已重测。
使用已有 ai_sni/.venv，显式本地测试数据库 URL（127.0.0.1:1，无连接）与虚构测试配置，
实际查询为内存 SQLite。测试不运行应用启动钩子、数据库迁移或百度服务。
前端无改动，未运行前端构建；本轮不声称全仓库或线上验收通过。

后续发布范围仅上述 SEM 后端文件，经用户另行授权提交/PR 审核后进入 main，再走独立
codex/production-sem-backend 同步及受控发布；migration=not-run。
驾驶舱接入由其负责范围单独集成，不能把 main 整体部署到 SEM，也不能复用 SEM 前端生产分支发布后端。

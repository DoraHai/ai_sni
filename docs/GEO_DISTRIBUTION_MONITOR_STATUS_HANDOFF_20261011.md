# GEO 发布后最新监测状态投影（2026-10-11，本地候选）

本批从 `b61e885627206029ff54bd6a572f6c1049b5dc25` 接续，只新增 GEO 原生只读接口及其测试。
不修改监测算法、数据库结构、worker、原程序或 SEM，不联网抓页、不重新发布。
中央后续从已回写任务的原生 publication_id 调用本接口，才能显示当前监测状态，不能继续把首次
登记的 `monitor_state=pending` 当作永久实时状态。

## 服务端接口与严格返回

```python
from app.geo.distribution_results import publication_monitor_status

value = await publication_monitor_status(
    session, actor_user_id, tenant_id, scope_id, publication_id
)
```

```json
{
  "module": "geo",
  "publication_id": 1,
  "basis": "public-text",
  "state": "observed",
  "evidence_source": "none",
  "observed_at": 1791705600000,
  "next_check_at": 1791792000000,
  "evidence_id": null,
  "code": "GEO_MONITOR_OBSERVED"
}
```

只返回这 9 个字段，不返回 URL、正文、adapt_meta、history、内部错误、外部自由文本码或图片。
code 由固定状态枚举构造，仅 ASCII，长度小于 64。

| 原生记录 | 返回状态 | 含义 |
| --- | --- | --- |
| `healthy` | `observed` | 曾有公开文本观察；不是完整页面/图片核验，也不是 AI 引用 |
| `pending` | `pending` | 原生监测已登记，尚未产生观察 |
| `unreachable` / `mismatch` / `version_changed` | 同名状态 | 原生最新异常状态 |
| `running` / `failed` / `unavailable` | 同名状态 | 接受统一合同中的原生状态，不主动生成这些流程状态 |
| 没有监测 entry | `not_queued` | 不补排队、不伪造时间 |
| 坏结构、未知状态、`captured` 或坏时间戳 | `unavailable` | 安全失败；`captured` 属于 SEO，不冒用为 GEO 观察 |

`healthy/observed` 必须有真实 `checked_at`；缺失不能返回 observed。时间只从原生带时区 ISO
`checked_at` 和 `next_check_at` 转成 UTC epoch 毫秒，未记录则为 null，不用当前时间或发布时间补齐。
时间范围与中央合同一致：0–4102444800000（2100-01-01 UTC），超界安全 unavailable。

当前原生 JSON 没有稳定、可靠的“自动/人工观察来源”或独立 observation evidence_id，因而始终
返回 `evidence_source=none`、`evidence_id=null`。`publish_mode=manual_export` 只是发布方式，
手动点击检查也可能执行自动抓页；任意元数据中的来源/ID 字段不能成为证据。

worker 中断保留上一次实际观察，并更新下一次复查时间。接口读取原状态和原 checked_at，
不会把一次执行器故障伪造成新的页面失败或新的成功观察。

## 实时授权与历史范围

调用当前 `authorize_scope`：实名账号有效、角色具有 GEO 资产和内容编辑权限、客户 GEO 服务有效、
项目与业务范围有效、当前顾问分配有效。再核对 publication → variant → task 链、task 客户、
business 和 prompt 是否属于该项目。无记录、跨客户/项目、断链、角色/账号/分配撤销均明确
HTTP 403 `GEO_MONITOR_SCOPE_FORBIDDEN`，不会被吞成 unavailable。原生 401 保留；403/404/409
规范为安全 403；5xx/结构问题返回 sanitized unavailable，避免把服务故障显示为撤权。

不调用 `load_source`、不要求原稿仍是最新母稿或当前已审核稿。后续正文改动、审核撤销或新增母稿
仍可读取原发布记录的历史监测状态及真实观察时间；本接口不会重新验证当前正文，也不会替它
产生新版发布记录。

读取仅选择原生身份字段和 metadata，不加载正文/发布 URL，不覆盖调用者待提交的 variant 对象。
`no_autoflush` 和连接级 savepoint 确保不会 flush 调用者待提交 ORM 对象，也不会 commit。
缺表等 SQL 结构故障返回固定 unavailable，并回滚本次连接 savepoint，调用者事务仍可继续读取。

## 验证与部署边界

最终 **100 passed，0 failed，0 skipped**：本批 35 个 PG 场景、原生结果 34、来源 PG 8、
最终发布门禁 1、监测单元回归 22。仅服务 503 故障场景注入纯 JSON 投影函数的异常；本批正常
身份/范围/事实/审核数据来自真实 PostgreSQL，未 mock 原生
授权或归属；旧来源/监测单元回归有明确测试替身，不能称为真实平台验收。

覆盖实际 pending→healthy/异常状态流转、原生 worker 故障保留历史观察、缺 entry、坏容器/状态/时间、
GEO 拒绝 captured、手动/接口发布方式不能推断证据来源、跨租户/项目/prompt、当前角色/账号/顾问
分配撤销、历史改稿/撤审/新母稿仍可读、缺表后事务恢复，以及读取不 flush 或覆盖调用者待提交对象。

仅使用自有 PostgreSQL `127.0.0.1:55507`、数据库/用户 `geo_ci`，测试 helper 强制检查连接；随机
schema 已清理，共享中央 55443 未使用。没有生产 DDL、生产 API、部署、真实平台读写或 SEM AI 接管。

- XML：系统 TEMP `geo-distribution-monitor-status-regression-20261011.xml`。
- XML SHA256：`f438946084ceaa4c53dea3baa643c82ab2607d25559439995e7828a13b773b08`。
- 证据：`GEO_DISTRIBUTION_MONITOR_STATUS_EVIDENCE_20261011.json`。

## 中央冻结后的实际 GET/JWT/PG 联调

针对中央干净提交 `4a15d242b234cc4a71ccb8c4885921eedebb9c57`，动态加载其真实 router、合同和
publication-results 代码。固定 adapter 导入本分支真实原生函数，未 mock 原生读状态或写入器。
实际原生登录签发 JWT，自有随机 schema 中应用中央三份 DDL 与原生结果 DDL。

**10 passed，0 failed，0 skipped**：新增 3 个最新监测 GET 场景，以及必要的原 7 个真实回写联调回归。

1. 已报告但未核验回写前拒绝 monitor GET；真实核验与原生回写后显示 pending。通过原生
   `outcome/store_state` 构造测试观察，再次 GET 返回 observed 与真实记录时间，而原始 writeback
   pending 快照保持不变。publication_id 从已写回任务读取，客户端传入的 999 不能选定另一对象。
2. 后续正文改动/撤审仍能只读历史监测；其他顾问、超管、设备、跨客户和实时角色撤权均拒绝读取。
3. 坏原生监测元数据只返回 unavailable，不回传私有时间/URL/history；所有 GET 不新增任务、原生
   结果或核验事件，未触发重新发布。

这些场景使用模拟设备回执、人工确认和观察记录，没有抓取真实公开页；证明真实服务/数据与权限
链路，不证明平台可达、页面/配图一致或 AI 引用。

- 中央 XML：系统 TEMP `geo-distribution-monitor-broker-frozen-4a15d242-20261011.xml`。
- 中央 XML SHA256：`807bf0ce8fff0093a4ad6f1c01c457af2d09afc3f5d7d57589615d2a05ac22d0`。
- 中央运行文件的 SHA256 与本地原生源文件 SHA256 均记录在对应证据 JSON。
- 最终随机 schema 剩余 0，自有 55507 已停止，共享 55443 未使用或停止。

SEM 的 AI 接管继续关闭，按用户要求最后推进。

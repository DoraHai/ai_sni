# SEO 发布后的页面检查调度与实时只读状态

本地候选；基线 SEO `ffce26e3`，最终中央实时监测协议 `4a15d242b234cc4a71ccb8c4885921eedebb9c57`。
本批不执行生产 DDL、部署、GitHub 操作、真实平台发布或真实外网抓取。

## 调度设计

`seo_scheduler` 追加 `run_seo_publication_captures`，每分钟运行，保留原有 15 个任务。
单批最多 20 条、并发最多 2 条，只扫描已提交的不可变 SEO 回写记录关联的自动 capture，
且中央项目当前为 running、当前项目 owner 与原回写实名顾问一致。
中央实际表名来自已冻结结构：`distribution_controls`（不是另造 `distribution_projects`）。
未关联中央回写的手工/站内截图不进入新增周期调度；原有入口继续可用。
关联以 publication 为准，包含从原生入口再次预约的自动检查，不能只恢复首次 capture ID。
在 LIMIT 前过滤实际重试/租约到期时间，20 条旧等待任务不能挡住第 21 条已到期任务；
JSON 时间字段先验证类型、整数及安全范围，缺省 running 使用既有捕获时间加超时窗口。

- 必须启用 SEO scheduler、外部动作与页面截图，demo 环境关闭。
- 缺少中央启停表或回写表时返回 unavailable 并记录固定日志，不绕过项目控制启动抓取。
- 执行前及保存结果前均核验租户/网站/module entitlement、有效实名顾问及角色、当前网站分配、
  项目运行状态、母稿/渠道稿审核/客户确认、原始来源 revision/digest 和精确发布地址。
- paused/ended 可保留历史发布及 pending 预约，但不自动启动外网；恢复 running 后复用原预约。
  若抓取中途暂停/关闭捕获，丢弃结果，保留原 capture 为 pending/nonterminal，暂停不消耗失败预算；
  恢复运行后仍用同一 capture。ended 明确停止，不能自动抓取。撤审/撤权/来源变更仍终止，不自动复活。
- 仍使用 `execute_page_capture` / `PageCaptureService` 的公共地址、重定向、SSRF 和资源上限检查。
  中央关联记录从原有 BackgroundTasks 入口执行时，也必须走同一调度门禁。
- 外链发现会覆盖 publication.link_discovery，因此实际门禁查询不可变事件账本；capture 上另保留
  `_central_publication` 标记，不能把临时元数据当作权限依据。

## 并发、租约和恢复

不新增表或生产迁移。已有 capture.warnings 的私有 `_publication_dispatch` 成员保存尝试次数、
随机 token、租约到期、实际重试时间和终止标记；原生截图响应过滤这两个私有成员。
每条检查使用独占 PostgreSQL session advisory lock，锁连接在外部读取期间保持占用，
**没有数据库事务跨越外网调用**。获取或释放锁时遇到取消/故障则废弃物理连接，防止池中泄漏锁。
claim、校验及结果保存顺序复用这条物理连接，不在持锁时从同一个 pool 再借第二条连接。
所有执行入口共用进程内最多 2 个非阻塞名额；忙时不排无界等待队列，保留原 pending 交周期调度。
真实 PG 的 1/2 连接小池、多入口测试验证无自阻塞，并在渲染时检查该 worker 的数据库会话为 idle。

原生行锁完成 claim，提交后才进入渲染。完成时再次锁行，对比 claim 时间及 token，旧执行不能
覆盖新租约。跨进程抢占、进程取消、锁获取中断、过期租约但旧 worker 仍在线均有真实 PG 测试。
崩溃留下 running 时等待租约到期再恢复，继续使用原 capture ID，不创建重复预约/发布。
租约为既有渲染超时加 60 秒；实际渲染仍有既有超时限制。

timeout/worker_error/storage_error/dispatch_unavailable 最多总计尝试 3 次，首次失败后 60 秒、
再次失败后 300 秒才可重试。次数和时间落库，重启不重置预算。耗尽后 `retry_exhausted`，
审核、权限、URL 等确定性问题终止自动重试。日志只包含 capture ID、固定状态/错误码、次数和重试标志。
本链路只有页面读取，不再次下发发布任务，不调用文章发布接口。
暂停结果、预算结算及 token 清除同事务提交；在第三次尝试暂停后即使收尾进程崩溃，
也不误判预算耗尽。兼容旧的“暂停结果已提交、预算尚未结算”状态，清 token 后只结算一次，
重复暂停扫描不返还已有真实失败次数。后置校验发生 SQL/取消等异常时删除本次尚未登记的截图。

## 服务端实时读取契约

```python
publication_monitor_status(session, actor_user_id, tenant_id, scope_id, publication_id)
```

精确返回白名单示例（合成编号）：

```json
{
  "module": "seo",
  "publication_id": 101,
  "basis": "page-capture",
  "state": "captured",
  "evidence_source": "auto",
  "observed_at": 1791730800000,
  "next_check_at": null,
  "evidence_id": 201,
  "code": "PAGE_CAPTURED"
}
```

- 重新鉴权当前原生身份、角色、租户/站点范围和 entitlement；403 直接上抛。
  可读取历史检查，不要求文章仍是原来的版本或仍保持原审核状态。
- 选择当前 scope、明确 publication 关联下最新真实 capture，按 captured_at、id 排序。
  不用首次回写响应缓存，不挑旧成功掩盖新失败，不将其他网站的证据混入。
- state 为统一允许集合中的 SEO 子集：not_queued / pending / running / captured / failed /
  mismatch / version_changed / unavailable；不产生 SEO 尚无依据的 observed 或“已收录”。
- succeeded 且有截图摘要/文件依据 → captured，**只表示页面截图**；不表示内容比对完成、已收录或效果提升。
  合法手工证据明确为 manual，自动证据为 auto，无依据为 none。
- observed_at 仅由真实已存检查/手工证据时间计算为 UTC epoch 毫秒；预约时间不是观测时间。
- next_check_at 仅使用已持久化的实际重试时间；无重试安排、重试终止或项目不运行则 null。
  它是最早重试时间，调度并发/负载可能使执行稍晚，不承诺恰好在该毫秒开始。
- 地址关联改变 → mismatch；worker 曾因审核/来源变化拒绝 → version_changed；错误码固定 ASCII。
  读取本身不检查线上页面、不重新审核、不消费配额、不创建任务、不更新过期状态、不 flush 调用方改动。
- 缺结构/存储故障安全返回 unavailable；内部 savepoint 不破坏调用方事务。返回不包含 URL、正文、
  storage_key、原始异常、核验 payload 或凭证。

中央显式读取接口应从已回写任务取得 publication_id 后调用此方法，不接客户端任意原生 ID。
本批未修改中央路由/工作台；已按上述固定提交动态加载中央实际 GET /publication-monitor，
实名 JWT/PG 联调验证自动及手工来源、pending→captured、当前范围/撤权拒绝、首次预约快照不变。

## 本地验证边界

新增 `tests/test_seo_publication_monitor_postgres.py` 使用专用本机 `seo_workflow_test` 随机 schema，
真实模型、实名 JWT、角色/审核和 PostgreSQL 锁。外部渲染边界为合成 CaptureResult，HTTP transport
被禁止；截图成功不是对某个真实平台页面的验收。
既有截图渲染测试继续覆盖私网地址/重定向等 SSRF 防护；截图 API、scheduler、原生回写一并回归。
原有 6 项中央 router→真实 SEO 回写与新增 3 项实时读取联调共同按冻结中央提交验证；
中央页面 UI 的浏览器验收由中央负责，本模块未将接口验证冒充完整 UI 验收。

## 最终冻结证据（2026-10-12）

- SEO 业务代码：`0259cfd280b31927a5c48c9208650657f3682672`，合跑时工作区干净。
- 中央实际读取：`4a15d242b234cc4a71ccb8c4885921eedebb9c57`，通过 git show 固定加载模块与 DDL。
- **198 项通过、0 失败、0 跳过**：原生 189 项（调度恢复 42、截图 API 13、截图/SSRF 54、
  scheduler 28、原生回写 52）及中央真实 JWT/PG/adapter 联调 9 项。1 条依赖弃用警告。
- 原始报告：TEMP `seo-publication-monitor-final.xml`；SHA256
  `a3cb7856fb6a4f7b08305dc3f8baea2a189747aee4f06a8d871a8a26b4b54acd`。
- 实际文件字节与 Git blob 双重摘要、逐案例边界及中央源文件摘要：`SEO_PUBLICATION_MONITOR_EVIDENCE.json`。
  worker 实际字节 SHA256 为 `36d9de7c7eb52932c89a7be4b45228717923b035cd141dd39ca9d6ffa2b1d794`；
  capture API 为 `dde84b3e5386e9754f658e4ae264fbfdfe6794779bcb87466adde7d1b7a722e0`。

本次最后收尾只更新证据/文档，不改变受测业务代码。专用测试库只清理本次随机 schema，未停止共享服务。

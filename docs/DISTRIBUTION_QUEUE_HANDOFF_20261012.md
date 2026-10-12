# 客户渠道配置、能力标注与自动入队：本地候选

本批从 `499102fd`（运行代码基线 `4a15d242`）开始，仅修改中央分发服务、独立 customer-workbench 和相应测试/文档。没有 fetch、push、PR、生产迁移、部署或真实发布；没有恢复 Computer Use、真实账号或会话操作。SEM AI 接管关闭，官网执行仅预留。旧评审包 `db235d06` 保持不变。

## 行为与授权边界

顾问按项目选择已经由超管绑定的账号及其内容类型，保存持久化配置并启停。启用渠道表示允许生成该渠道的排队意图，不授予正式发布资格；项目暂停保留配置与新稿排队，停用渠道停止新入队并保留历史。结束项目不能恢复。超管维护全局排队授权及现有账号时区、时段、日上限、间隔和暂停规则。顾问只能选择并收紧，不能宣称平台能力。

能力上限由服务器代码登记，按渠道、内容类型、账号绑定和授权计算。公众号文章/小红书图文当前标注人工发布，列出系统队列/复核/节奏步骤及人工登录、编辑、上传、正式发布和公开作品核验步骤。实页通路未验收，所以 `executable=false`、`automated_publish=false`、`real_channel_verified=false`。全局授权也不会升级能力。官网为未接入且不能启用。后续渠道可在独立目录扩展；设备 v1 `Platform` 仍只认两个冻结值。

规划队列与旧设备执行任务分表。后台不创建 device task、grant 或 publication grant，也不删除旧人工确认字段。当前手工发布任务继续走原授权、未知结果核查和公开内容核验。队列按客户/项目/渠道/平台真实账号/variant/draft_version 唯一；同平台账号同项目只允许一个启用的设备绑定配置，换设备不制造重复队列项。正文或素材变更生成新 draft_version，审批变化仍更新原队列项。原设备任务、账号占用及不可变回执不受规划状态修改影响。

本批 channel-permission/project-channel **仅控制新增自动排队**，不改旧版 `/tasks` 人工 handoff/publish 的独立逐稿授权流程，也不撤销已有任务。界面统一称“自动排队授权/排队配置”，并明确旧版逐稿人工授权独立；停用不等于撤销所有发布授权。旧入口仍需原生当前审核、顾问逐稿确认及人工发布确认，项目暂停/绑定停用会阻断旧任务推进。实际 API 测试覆盖排队关闭不新增意图、缺人工确认仍拒绝、原人工授权可用、项目暂停后拒绝新人工任务。统一发布权限整合属于后续实页执行验收批次，不能从本批排队授权推断具备平台执行权限。

顾问看到目标渠道、账号、稿件编号、等待原因、最近复核和下次时间，内容版本放详情。正文仍通过原生审核入口。客户交付页不增加执行控制。缺接口/鉴权撤销会清空前端授权数据，未知写入不会自动重试。

## 真实后台入口与窄来源契约

独立入口 `python -m scripts.distribution_queue_worker --once` 可供既有 scheduler 调用；不加 `--once` 时默认每 30 秒恢复扫描持久化配置，间隔限定 5–3600 秒。要求显式 `DATABASE_URL`，不执行 DDL、不依赖 GET、不调用平台或 AI。集成环境需要按既有进程管理挂载此独立 worker；本批不修改整个 `app/main.py`、共享模型或其他工作树，也不声称生产 worker 已启动。

每轮最多处理 50 个最久未检查配置；每个配置一事务。来源页和既有队列点复核分别最多 50 项，持久化独立游标；成功页面与游标在同一事务提交，进程重启或并发 worker 不重复入队，到尾页后重新复核。失败只回滚受影响配置，另记持久化扫描原因；不把上一轮快照当成本轮成功。scope/account 锁保护配置复读与账号去重；独立账号可继续。

原生优先提供：

```python
list_intake_candidates(session, actor_user_id, tenant_id, scope_id, platform,
                       *, after_variant_id=None, limit=50)
# {"items": [metadata], "next_cursor": int | None}
load_intake_candidate(session, actor_user_id, tenant_id, scope_id, variant_id, platform)
# metadata | None
```

严格 metadata 五字段：`variant_id` 正整数，`draft_version` 稳定内容/素材版本（1–100 位字母数字下划线连字符），`source_revision` 同格式或 null，`readiness` 为 ready/awaiting-review/awaiting-adaptation，`reason` 为 1–64 位字母数字下划线。按 variant_id 升序 keyset；next_cursor 仅更多项时为末项 ID，否则 null。ready 才可带 source_revision。审批状态不能改变 draft_version。点复核先检查当前权限，只有不存在/非最新/不属于完成集合时返回 None；权限、结构或 SQL 错误必须报错。

接口使用传入连接、no-autoflush、当前存储状态读取，不返回正文、素材或凭证，不网络、不 flush/commit，不开持锁互等的第二连接。中央不信任 readiness 授权，ready 每次仍走 `core.source` / 原生 `load_source` 审核门禁并核对版本摘要。明确 stale/not_found 原生码使旧项失效，其他审核失败归待审核；pending 旧项通过点复核失效，不以“不在某一页”判断失效。

没有 intake 接口时仅兼容旧 `list_sources`，明确显示“仅已审核来源扫描；待审核稿发现尚未接线”。这个兼容路径不能解决原生旧列表最新 50 项的覆盖上限，不能作为完成稿全面发现的验收依据。原生 intake 挂载后才显示完成稿分页扫描。中央没有伪造原生完成事件接线，响应始终 `completed_draft_events_connected=false`；本批选择可靠分页后台恢复路径。

## 等待与审计

队列可为待审核、待适配、待授权、项目暂停、定时等待、待介入或旧版本失效。账号结果未知/占用/验证码/掉线/结果冲突读取原账户调度并转待介入；不释放既有未知结果占用。缺账号系统规则或时段/额度未满足显示具体等待原因。当前通过全部门禁仍待实页适配验收，不能派发。

入队、目标状态变化、旧版本替代和扫描失败/恢复写 append-only `distribution_events`。状态变化日志 action 为 `queue_<目标状态>`，target.action 保存原状态，result 保存原因，task_id 是队列记录 ID；扫描日志无设备 task。不保存凭证、Cookie、正文、原生错误或私有 URL。相同状态/原因的重复扫描不重复写日志。

## DDL 与集成

新增候选 `scripts/distribution_queue_schema.sql`，顺序 control→scheduling→publication→queue。新增全局授权、项目配置、规划队列、扫描进度四表；不替换旧任务/占用表。运行时不建表。生产迁移需统一链、审查和备份/回滚计划。回滚应先停 worker 和新写接口，保留队列/审计数据导出后再按正式迁移流程处理；本批不执行生产迁移。

新增实名 API：GET channel-catalog（超管）、project-channels、queue；POST channel-permission（超管）、project-channel。旧 scope 能力开关保持关闭，旧手工任务 API 和设备协议保持原有约束。测试 DDL 只在隔离测试 schema 执行。

## 测试证据

后端运行代码冻结为 `f5ed86697c4e8c3ce8d4854d888dcf5090064368`。最终工作台展示修正提交 `8c0ba5cfd3044fe87e53e41250a52cc089f51e45` 只将 SEO/GEO 原生等待原因映射为中文，后端逐字节不变。后续证据文档提交不改变运行代码。

- 中央完整回归 **91 项通过、0失败、0跳过**，含真实隔离 PostgreSQL/JWT、账号并发/跨客户/授权撤销/素材/回写/监测，以及实际 FastAPI/TLS→Node/Electron 合成素材交接。报告 TEMP `distribution-queue-central-final-20261012.xml`，SHA256 `c5eefff80502873e85fc52a219df138470519654249b22a35669020699fceb3c`。
- 新增队列最终 **14 项通过**，其中最后补充的是排队开关与旧人工授权边界的直接 API 测试；与上项覆盖有重叠。报告 TEMP `distribution-queue-only-final-20261012.xml`，SHA256 `ee8f49bdab81e57dd25802129a5672d04471136ba7b818bb9b300b04e5d5eb61`。
- 全工作台契约 **181 项通过**。分发前端 **37 项通过**，其中 **3 项为构建后的实际 Edge**：待审核队列显示渠道/账号、选择/停用、超管能力授权/官网不可执行、移动布局、权限清理、旧发布核验回归。浏览器为合成响应，不连接真实平台。
- 干净工作台构建 `sourceTreeClean=true`，绑定最终工作台提交 `8c0ba5cf`；manifest SHA256 `39a65243b6afbaa1b9f6acd000ac9e53504ddc17a86aa8fe4ec11341d3fbbb4a`。测试用同一源码构建，干净构建只更新提交追溯信息。中文原因映射另复核分发契约34项和受影响实际Edge1项通过，覆盖有重叠。源码、Git blob、产物和各报告摘要见 `DISTRIBUTION_QUEUE_EVIDENCE_20261012.json`。
- SEO 精确原生 HEAD `139cc7f57650afb1e83930149b6fac33cb9f861a`，接口 SHA256 `4ab7cc1287ee90c45230042f488526357c745907a649db4642a28f51589fb890`。本树脚本 `scripts/verify_distribution_seo_intake.py` 读取其真实模型/fixture/adapter，与中央实际 router/JWT/4份DDL/worker 联调，覆盖待审入队、审批沿用 ID、当前审核、全局排队授权、规则满足仍不可执行、暂停恢复、新 variant 失效、撤权拒绝、无 device grant 和 GET 只读。报告 TEMP `distribution-queue-seo-integration-20261012.json` 绑定 runtime commit，SHA256 `1c2718e34e53d77e121cfaa63db8d84d2578960682849a882f155171ae148b99`。使用指定 Python 与本机 TEMP `seo-test-pydeps` 既有可选依赖，没有修改共享 Python 环境。

隔离数据库仅新建于 TEMP 独立目录，监听 `127.0.0.1:55443`，数据库 `distribution_control_test` 与 SEO 联调 `seo_workflow_test`、用户 `distribution_test`；各测试使用随机 schema 并清理。平台与来源元数据为合成输入，Edge 只访问合成响应页面，不使用真实账号；任何此类测试都不是实页发布验收。各组有覆盖重叠，不相加为端到端发布案例。

GEO 最终 HEAD `ba713f06da330362cd0539531e4edd3216a09d78`，运行代码 `bb996007e352e2eff5f893da985cb07f63e907f5`，接口 SHA256 `9536a0fc94a9f42893301f5e0aa7d34d321ed9b6a57642135e7181701fd395b2`。总回归 **86通过、0失败、0跳过**，准确组成是75项原生测试（32项新增＋43项回归）与11项实际中央联调，再用冻结中央 `f5ed8669` 的11份运行代码/DDL进行 **11项复核通过**，不另算独立场景。证据 JSON SHA256 `a766293b1b36231120370c6b6f82127eec08aa7a03a4f01ec48cf06233ecb1d5`。已逐项核对本树当前11文件与其冻结摘要一致。覆盖真实原生/JWT/数据库待审入队、审批沿用队列ID、正文和新稿替代、pending点复核、pool_size=1及已有tenant/task锁；没有生成设备任务、发布占用或原生发布记录。其独立loopback `127.0.0.1:55507/geo_ci`随机schema已清理，实例已停止，未触及本批55443。

本批自建55443测试实例已停止，测试schema已清理。原生 SEO/GEO 精确候选与集成证据由2.0协调，中央只读核对，不整体覆盖异构后端基线。统一生产挂载、候选DDL审查/迁移和真实平台验收仍未进行，本批本地通过不代表生产上线。


## 第一批完成与下一批边界

第一批已完成本地客户渠道排队配置、服务器能力上限、真实原生元数据自动入队与重启恢复、顾问等待状态和审计，以及对应隔离验收。中央不需要每篇人工点击入队；旧逐稿人工授权独立保留。源完成事件没有伪称接线，当前采用可运行的后台分页恢复入口。

下一批才推进AI在已授权规则内的排期建议与确定性校验，以及各实际平台的账号身份、编辑器、原生上传、正式发布和结果确认验收。AI不得新增账号、扩大权限、放宽上限或自行调用任意发布工具。登录成功、合成页面和本批联调均不等于实页验收，未验收路径不能升级全自动。生产worker挂载、统一迁移及部署仍需正式集成流程；SEM AI接管仍最后推进且关闭，官网仅预留。

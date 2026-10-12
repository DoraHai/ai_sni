# 现有客户稿件独立分发验收（2026-10-12）

本轮使用生产只读白名单快照，在独立数据库、测试身份、设备、证书和客户端目录中走实际原生审核与中央自动分发。生产客户、网站及账号没有被修改；正式发布、付费 AI 和 SEM AI 均关闭。

SEO 与 GEO 均走完顾问启动、自动排队、计划模拟、自动派发、多号通 GUI 领取/预览/导出和人工交接确认。随后两项目由顾问暂停，绑定经管理员撤销，正常重启后仍各只有一个成功任务和一个交接完成回执，未重复派稿或计量。交接成功只证明这条素材交付链通过；首次 GEO 人工交接等待未定位原因，不能据此宣称所有发布场景完全稳定。

## 环境及版本

- 新中央验收树：`distribution-real-customer-acceptance-20261012`，基线 `6c8fd505c1eba7ba4b0b616f9037793177ea1ddc`。只修改验收 scripts、专用静态页面及本报告；中央业务、共享鉴权、原生 SEO/GEO、SEM 和多号通源码均只读。
- 新 TEMP 直属目录：`distribution-acceptance-full-flow-20261012`。PostgreSQL `127.0.0.1:55473`，SEO HTTPS `55851`，GEO HTTPS `55852`；两库分别使用隔离 schema。HTTPS 验证新专用 CA、IP SAN、签名和日期，不忽略 TLS。
- SEO 原生冻结：`b4d8387123355348f79e26ea2838585c5106a4b9`。GEO 原生冻结：`46dacbd805afc00f37eba344306fde004039efed`。
- 输入快照 SHA-256：`f75d382a54ec33f0c892cc4c6afcc17b082c130cc1b58236fb4dde48e383f609`。只有经白名单采样的客户稿件和事实核查元信息；生产认证、渠道凭证和 Cookie 未复制。全文和测试口令仅在私有 TEMP/隔离库，未提交 Git。
- SEO 0105 在新隔离库执行了实际原生 migration，并核对真实 revision 和迁移源 SHA；中断恢复不能仅凭 import-report 文件跳过迁移。没有伪造 schema stamp。
- 历史 12 项根窗口 API 权限检查属于 `f1dc68d425a91088823a216327dc68b0be3d5c40`，原文件另存为 `*-f1dc68d4.json`。SEO 主链运行于 `f27cd2dbc82c087bfeac64eebdc4a3e473ebb910`；GEO 主链运行于 `1171bed7b3b3cdd0216d6a5b01743db5d969b63b`。最终根窗口重新执行12项实际 HTTPS 权限检查，属于下述7a585f运行 pin，不能将历史检查改标为最终检查。
- 最终可运行验收 scripts/UI 代码与收口服务：`7a585f5425ac2c1269f37448cdb840f803e8830c`。该 pin 在双方客户端 shutdown 后一次正常重启；随后仅提交 docs，服务 health 继续记录此运行 pin。
- 多号通 SEO 主交接：`a63b3c89d6ab9161805773341e9d1ef86b690ae7`。独立终态历史修复与 GEO 主交接：`889abf6e7d27f228f9306f22ba607ca2d9c59345`；8 个运行产物 SHA 由本轮收集器只读核对，具体值在 JSON 索引。

旧 `distribution-control-20261011`、旧 `distribution-acceptance-customers-20261012` 及其 55463/55841/55842 服务未修改或停止。

## 实际流程与边界

| 环节 | 本轮实际执行 | 人工/顾问边界 | 验证范围 |
| --- | --- | --- | --- |
| 已有 SEO 稿件 | 保留原 master60/百家号 variant1。实际 DOM 创建本地母稿61并提交原生内部审核 | 独立本地审核人批准；分配顾问以 `advisor_proxy` 确认精确版本和 payload hash | 原生 API 和验收 DOM；不等于真实客户授权 |
| SEO 微信适配 | 原生 `wechat_browser` 连接，无发布 secret；非 AI 适配，生成 pending 渠道稿2，再独立审核批准 | 审核及客户/顾问确认未自动跳过 | 实际 DOM/API；真实微信编辑器的排版和上传未验 |
| GEO 事实及稿件 | 使用原生 `/facts/4/verify`、`/facts/6/verify` 记录当前官方来源短引文、严格译文及本地测试核查人。创建同 tenant1/business13/prompt71 的本地 task13副本 | 这是人工修订和事实核查，不是 AI 自动产出的已合格原稿 | 实际原生 API；未声称 GEO 原生 Vue 编辑界面通过 |
| GEO 定版及重审 | 实际母稿23v4和 preview 经五项确认生成 manual variant13，重新执行规则/事实/lint/品牌/平台检查 | 顾问自批403；独立本客户测试 JWT 批准当前版本。稿件变更会重新失效 | source 与 native intake 的 revision 完全一致 |
| 顾问启动 | 项目初始 paused；已分配顾问通过实际 DOM resume 当前 revision | 客户没有项目启动、暂停或审核按钮；服务端控制接口也拒绝客户 | 两模块独立项目范围 |
| 自动排队/计划/派发 | 实际 worker 自动扫描已配置渠道，只拾取当前合法 source；实际 managed gateway 计量，实际队列及 dispatcher 生成 handoff task | 计划本轮明确使用进程内模拟器 `sim-local-distribution-planning`，不证明真实供应商 AI 提案质量 | 未逐稿 POST 创建任务，未抢客户端 lease |
| 多号通 GUI | 专用新 profile、TLS/pair/capability/账号配置；由唯一 GUI 客户端领取、预览、导出并确认交接 | 宿主没有登录或打开真实发布平台；交接完成不等于发布完成 | 中央 receipt/ledger 记录 `HUMAN_HANDOFF_ACCEPTED`，publication false |
| 暂停/撤销/恢复 | 已完成交接后顾问 DOM pause；管理员真实 binding revoke，原交接元数据保留 | 不伪称测试过实际上传中强制停止或平台事故恢复 | 最终同库正常 stop/start 后检查 task、receipt 和计量无重复 |

原百家号稿件没有接入中央正式发布通路。本轮正向渠道为 `wechat-article` 的素材交接。网站修改接口仍为预留；真实渠道内容填写、图像上传、提交、公开链接核验、收录/引用监测正向链均未在本轮触发。SEM 未变更。

专用交付验收 DOM 隐藏的是执行和内部审核按钮。GEO 客户在原生 API 对本人客户范围内的当前稿件作内容确认/review，是本轮明确保留的限定写入例外：实际请求200，顾问代为自批403。项目启动/暂停、跨客户读取和正式发布仍不属于客户权限；不能将交付页面只读表述为客户所有原生审核接口都禁止写入。

## 保留的失败和修正

1. 原 GEO article17v4/preview2 的 preview 门禁和原样质量缺口保留。本轮正向是由原稿派生的本地人工修订副本，不是原稿不变即可自动合格。
2. 新隔离库最初默认本地时区使 article18/variant5 的版本时间晚于 UTC 客户审核时间，原生 source 保守409。仅修正新 owned PG/engine 为 UTC；旧时间及失败记录未修改。后续 task12 的未来 updated_at 历史仍导致 article19/variant7 非 latest，继续409，没有排序或门禁绕过。
3. task13/article20/preview9 缺少当前文稿日期，真实质量检查拒绝。article21 的 outline 日期曾通过，但不是最终交付稿；article22 非标准日期说明被严格事实分类拒绝。最终 article23 通过实际原生保存，正文使用原生支持的可见 `草稿生成日期：2026-10-12（非来源更新日期）`，同次 outline 记录真实 UTC 保存时间；标题/brief 明确本地验收修订。没有修改事实分类器。
4. SEO 第一张隐藏 Electron 窗口的最终截图画面仍停留在旧登录面板，不能作为 approved workspace 证明。改用实际 offscreen paint、两次 RAF 和 fresh capture，随后只读重拍当前已审核/paused 状态；没有重放审批。根窗口独立查看新 PNG，DOM 与像素一致。旧 PNG 保留为失败证据。
5. SEO 首次多号通交接的中央终态和 SQLite 审计正确，但 GUI 历史在 grant 正常撤销后不可见，属于实际呈现缺口。多号通唯一开发窗口另开独立候选修复当前授权范围内的终态元数据历史；不恢复旧 grant、不回传正文、不修改中央或本验收树。
6. GEO 首次 GUI 人工交接确认停在 `HUMAN_REQUIRED`，outbox0。客户端后来在同一任务/同一版本/同一租约合法恢复，得到 seq4 `HUMAN_HANDOFF_ACCEPTED`、outbox0，当前历史可见，重启不重复。首次没有捕获具体 UI/HTTP 拒绝码，原因未定位，仍待补错误诊断；失败 proof `7546f484aa53dd64a1196a92f711e8d84774892451481935fd5c6151eedbf6b2` 保留，不能称该阻断根因已修复。

本轮当前 GEO 正向 API journal 有 10 步，包含顾问自批403和客户当前版本审批200；之前的 fact verify、task create 和非 AI preview 创建另有实际原生请求。SEO 完整原生审核/适配验收 DOM 记录11项操作，独立会话延迟验收6项；两模块各有启动2项、客户交付 DOM 3项、暂停2项，以及暂停后安全收口11步 HTTP。它们包括登录、状态读取和重叠门槛，不加总为独立测试案例数。最终复核还断言各项目唯一任务、唯一接受回执、各一条模拟计量，零原生 publication、零中央 publish reservation。

## 证据及复现

最终非秘密索引为同目录 `DISTRIBUTION_REAL_CUSTOMER_ACCEPTANCE_20261012.json`，由 `scripts/distribution_acceptance_evidence.py` 生成。收集器必须同时确认两项目已暂停、binding 已撤销、唯一 task 成功、唯一交接确认、零原生 publication、零中央 publish reservation、计量为唯一模拟请求，并核对运行时实际业务/静态文件 SHA 后才写报告。

私有 TEMP 中保存真实 API journal、source/intake 版本摘要、只读 SQL checkpoint、中央控制检查、实际 DOM 状态、fresh paint PNG 和多号通 GUI 证据。索引只记录白名单元数据与文件 SHA，不包含正文、译文全文、路径密钥或口令。测试计数各有重叠，不能与此前 232/145/108/478 项累计为新验收总数。

三份独立多号通 GUI 证明分别为：SEO 主链 `04357c0fa3e4e5deca3044c8a5f622d17674b825b0d3855d964e42d5271bf55f`，历史修复 `07f7f1849b7b3906602820cd87d40198e1c295dbc6792bd108d294e53d4f8057`，GEO 主链 `a0cf190b0926b10c55ce4d6f4665e05543ce2775b366988e15b97897db7fbdab`。根窗口另外独立查看实际 PNG 并核6个真实导出文件的 SHA；其 `root-mht-artifact-readback.json` 和最终服务/原始六条数据/API 权限检查文件以原文件 SHA 收入索引，检查属于哪个 runtime 以其实际记录为准。

根窗口最终实际 HTTPS/PG 只读复核通过：两项目 paused/rev4、两 binding 撤销、每模块一个成功任务/一个 accepted 回执/一个模拟计量事件、零发布；实际健康与54项中央/验收文件 SHA、8项多号通产物 SHA 均匹配。原始6条内容及关键字段逐项对输入快照完全相同；多号通两模块6个实际导出文件 SHA 也匹配。没有设备 lease exchange、来源编辑或审核重放。

| 最终独立只读记录（新私有 TEMP） | SHA-256 |
| --- | --- |
| `root-final-runtime-readback.json` | `c517948627747533c36ee82793eaea636f8eef13dba6c50f3f1e758c69dccaef` |
| `root-source-boundary-check-current.json`（8项 actual HTTPS） | `7d7ea9a3fa94295dc5056011fe706abe1e424cae9cd831a531d03056286a8add` |
| `root-customer-control-check-current.json`（4项 actual HTTPS） | `eee5edcfa0a56491290c7985f4b554a5db021e81061560ecad3b0c9996115365` |
| `root-native-original-readback-current.json` | `470721689d3a70f72815aadf8e9e80364e66a1ae926ba0159581c5f4ac9eab95` |
| `root-mht-artifact-readback.json` | `d36a8ccfc4442c9b1e6808fd2c570248e981018390ea2201baf06f056d7033cc` |

```text
python scripts/distribution_acceptance_probe.py --root <精确新TEMP根> --module geo geo-fresh-copy
python scripts/distribution_acceptance_probe.py --root <精确新TEMP根> --module geo geo-date-revision
python scripts/distribution_acceptance_probe.py --root <精确新TEMP根> --module geo intake
electron scripts/distribution_acceptance_ui_check.cjs <精确新TEMP根> geo-start
# 由独立多号通 GUI 执行交接；中央不调用设备 exchange 抢 lease。
electron scripts/distribution_acceptance_ui_check.cjs <精确新TEMP根> geo-customer
electron scripts/distribution_acceptance_ui_check.cjs <精确新TEMP根> geo-pause
python scripts/distribution_acceptance_probe.py --root <精确新TEMP根> --module geo close-binding
# 两个客户端宿主均 shutdown 后，正常重启 owned 环境，再读两模块 checkpoint。
python scripts/distribution_acceptance_probe.py --root <精确新TEMP根> --module geo observe
python scripts/distribution_acceptance_evidence.py --root <精确新TEMP根>
```

这些是带状态前提的复现步骤，不应在已有审批/交接数据上重复执行写操作。探针不 mock 原生身份、审核、事实核查或结果写入；原生正向通过也不代表生产已上线或真实平台发文已验收。

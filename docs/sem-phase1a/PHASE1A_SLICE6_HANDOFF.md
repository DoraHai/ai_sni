# SEM 阶段1a第六刀交接（task15）

## review19_out.md 修复（修复轮19）

本节取代下方首轮交付的当前状态；下方原提交、计数、CI、Cursor及“外部文件”说明均为 b06dd187 历史证据。本轮直接处理该只读审查，不额外运行 Cursor 或联系任何人。完整阶段1a仍未完成，PR #824 保持 Draft、base=slice5/e6519f5b。

- 重要1：三份交接文件已纳入本分支 `docs/sem-phase1a/PHASE1A_SLICE6_HANDOFF.md`、`docs/sem-phase1a/status15.md`、`docs/sem-phase1a/PLAN.v12.md`。README/HANDOFF_INDEX 提供仓库相对链接，checkout 后无需仓库外路径即可读取；同名外部文件逐字节同步；本目录 .gitattributes 仅对这三份文件禁用换行转换，允许 CR 行尾并保留其他空白检查，以保证跨平台 checkout 的原始 SHA-256。PLAN.v12 原备份 SHA-256 保持 `9cac329bb6d1273f5149dc8b73a1930f29a283f7bbce61c9c69e9fb66e033fe2`，未改 PLAN 或其备份历史内容。OSS 同步根键与 `docs/sem-phase1a/` 键，最终文件 SHA-256 与精确 head/CI 证据保存在 `REVIEW19_SHA256_MANIFEST.json`，避免交接/status 自引用。
- 重要2：管理六字段响应无法判断用户停用/角色/grant代次等当前可写条件，采用审查明确允许的统一文案方案。授权页持续显示“是否可撤以服务端为准；申请撤销时会核验当前授权与可写顾问，按钮可点不代表允许撤销”；按钮改“申请撤销”，移除只按 activeCount 禁用。权限/busy/过期列表仍禁用；后端两种409保护、事务/账户锁、拒绝后零绑定和审计写入均不变，不扩字段或权限。
- 新增前端回归：两种保护409经真实 createShadowApi 撤销路径传播成同一末条保护提示，失败不刷新/不报成功，核对精确请求路径和scope；六路由×三角色真实 SFC SSR 对授权页核验新的服务端决定文案。既有后端唯一绑定、顾问+只读客户、失效顾问和并发拒绝测试保留并重跑。
- 小建议已处理：批次60秒/请求90秒常量明确为显式装配层责任，本单对象适配器不强制这两类 deadline；`_key` 仅匹配一次并复用结果。未新增装配、SDK、环境变量、配置开关或真实OSS连接。
- 重要设计说明（非必改）保留：账户行锁只能串行本服务同账户变更，不防 DBA 直改或其他身份/grant 生命周期变化。生命周期治理、迁移与锁策略需另批，本轮不扩大范围。
- 其余建议：既有 build 已实际执行新增 shadow 脚本，本地构建与验证通过；本轮继续核对远端 sem-frontend-build。相对 e6519f5b 的 `.github`、`app/config.py`、`app/main.py`、`app/security/auth.py`、`app/baidu`、全部迁移零差异；git diff --check 已执行，将在提交前复核。没有待处理的琐碎建议。

本轮验证与精确提交/CI状态见下方“修复轮19 验证结果”及同目录 status15.md；最终文档提交的检查证据另存 OSS 清单。只读审查无需授权上线，不合并/部署/force-push，不触生产/.env/真实客户数据，不请求 reviewer/assignee，不联系任何人。

首轮历史终验时间：2026-10-30T11:45:37.911006+08:00。开发起止见status15.md逐步记录；仅task15三个授权事项，完整阶段1a仍未完成。

基线已核实：远端slice5=e6519f5b37d06f24a2c5a7013860f981106f5eff，#823 open/Draft；新worktree D:/SNIPERS国内版/ai_sni-sem-phase1a-slice6-20261030，新分支sem-phase1a-shadow-slice6-20261030。普通提交/推送b06dd187587f33d7528c4f2f818900a8300b6adf，工作树干净；[Draft PR #824](https://github.com/DoraHai/ai_sni/pull/824)，base=sem-phase1a-shadow-slice5-20261029，叠#823。没有合并/部署/force-push/生产操作/联系人/reviewer或assignee请求。

模型遵循任务指定gpt-6.1-sol/high，不另声称可独立核验底层模型身份。Cursor composer-2.5仅--mode ask只读、无--force；首轮未信任失败后仅加--trust。Shell git diff被只读模式拒绝，终轮通过TEMP中包含新增文件的真实unified diff和指定源码交叉核验，退出0、无剩余阻断/重要缺陷，不声称Cursor实际运行git diff。首轮授权变更成功/列表刷新失败误显示空表问题已修为保留旧表、明确已保存/刷新失败并禁用操作，补helper回归；多图部分失败回滚与ShadowStore协议亦补。仅最后增加原生PG列表断言和成功日志标记，不改运行行为。

# SEM 阶段1a第六刀（task15）

仅实现本刀三项，完整阶段1a仍未完成；Draft叠slice5，不可合并或部署。现有工作台新增「首次接入 → SEM 影子规划」与系统设置下的账户授权管理，五种页面按定稿布局复用现有橙色主题、Vue/Element Plus/session/client。六个前端路由包括详情与导出；来源提交使用原#823完整契约（链接、长文本、可选PNG/JPEG/WebP、10MiB/张/10张/30MiB合计），不抓页/OCR/模型。保存来源201后可单独创建影子规划，并核对来源理由生成内部建议。真实预算帽/既有资产未核验，P5/P6继续阻断；导出仅内部Excel且有审计，客户只读不可导出。未授权/版本冲突/存储503显示明确错误，不假装成功。

为真实列表新增GET /api/v1/sem/phase1a/shadow/accounts/{account_id}/plans?tenant_id=...&offset=0&limit=50（上限100），生产principal每请求重核后check_scope(write=False)，数据库按payload精确tenant/account过滤。响应只有plan_id/version/product_line_id/pages/validation/execution_enabled六项元数据；索引并不证明来源有效，详情/Excel仍逐次复核来源hash/新版本/附件字节。全局管理员管理账户授权仍走require_admin及同事务DB重核，不获得来源/规划读取权。实际main端点矩阵扩为16×29，原未列执行路径继续关闭。

共享鉴权唯一必要变化：app/security/advisor_request.py的SEM_SHADOW_READ增加精确的phase1a/shadow/accounts/[0-9]+/plans GET。原因是#823没有列表端点；影响仅该账户索引读取，仍经模块与ProductionPrincipalAdapter检查。SEM_SHADOW_WRITE、管理路径、JWT及其他既有顾问写门禁不变。前端shadow路由需登录，菜单让已识别顾问可见；所有账户权限仍由服务端决定，不新增角色或功能开关。

附件新增app/sem_phase0/oss_attachments.py的OSSPrivateAttachmentStore，显式注入预配置SDK bucket，无SDK导入/环境读取/凭据值/网络初始化/应用装配。建议配置名SEM_ATTACHMENT_OSS_BUCKET/ENDPOINT/REGION/ROLE_ARN等仅为外部构造契约；不写app/config.py、不新增环境变量默认值。put_object强制x-oss-forbid-overwrite=true、private、SSE-OSS(AES256)，不先HEAD后覆盖；精确保留sem-sources/{tenant}/{account}/{page}/{revision}/{ordinal}-{sha256}。写前验证键/字节SHA-256，条件冲突或响应丢失则限量回读，长度/hash一致才幂等成功；其他冲突失败。读流分块限量并关闭，固定脱敏错误。仅连接/限流/临时错误可重试，最多3次，0.3/1秒退避；建议连接3秒/I-O10秒/单对象20秒/批次60秒/请求90秒为常量。SDK socket超时不等于绝对期限：上线装配必须另审SDK版本、经deadline约束的transport/worker及整批期限；本刀没有生产装配或云端验收，不能据此上线。ProductionServices默认attachments=None仍503。

授权撤销在既有账户锁及事务内，未写revoked_at/审计前检查：撤后无未撤销绑定409/LAST_GRANT_PROTECTED；剩余绑定没有有效可写顾问409/LAST_WRITABLE_ADVISOR_PROTECTED。顾问须用户启用且未锁定、当前角色符合现有is_advisor、精确顾问grant代次有效、默认客户grant存在。仅客户只读绑定不算保留可写顾问。两错误均绑定/审计快照不变；并发撤销串行后最多一条成功。幂等撤销保留；空账户GRANT_ACCOUNT_NOT_INITIALIZED不变。此保护仅覆盖本服务revoke，角色停用、其他grant撤销、模块/账户变化仍可能使顾问失去可用性，需独立生命周期治理，不声称全局永不失去顾问。

修复轮19后界面使用统一服务端决定文案及“申请撤销”，不按绑定行数判断可撤；最后可写顾问由后端实时判断并返回可读提示，不向前端泄露额外用户资料。变更成功后列表刷新失败保留旧记录、提示已保存但列表过期并暂停操作，人工刷新成功后恢复；上下文切换丢弃旧响应。

测试使用原TEMP受保护启动器，禁止真实.env和网络；内存OSS SDK stub仅测试。覆盖幂等/冲突/错误hash/路径/限量读/临时重试/权限不重试/并发同键/单图与多图部分失败数据库回滚（允许留不可达孤儿）；实际main既有显式内存附件201链继续通过。SQLite与现有CI临时PG测末条、只读剩余、停用/锁定/角色/顾问grant/默认客户失效、双撤销以及零副作用。前端无新依赖：六路由×三角色的真实SFC SSR、表单按钮、图片边界、错误/API/时区和授权刷新失败回归纳入npm run build，CI配置不变。最终计数、Cursor限制、CI及OSS证据见外部PHASE1A_SLICE6_HANDOFF.md和status15.md。

上线另批：真开私有桶/地域/RAM/ACL/密钥管理/SDK与绝对deadline装配、真实配置变量、请求体/锁等待/并发压测、备份恢复、初始化书面名单/脚本/PG迁移窗口与最小权限、孤儿对账/清理与生命周期/留存机制、真实预算帽与资产核验。无新迁移、sem_runtime扩权、触发器绕过或生产操作。无百度同步/OAuth、CI/.github、app/config.py、JWT、execute/upload-to-baidu/enable/customer-confirm/auto-pause变化。不合并/部署/force-push，不联系任何人或请求reviewer/assignee。

以下第五刀及更早记录均为历史，末条可撤与无前端描述已被本节取代。


## 文件清单

- app/security/advisor_request.py
- app/sem_phase0/oss_attachments.py
- app/sem_phase1a/grant_management.py
- app/sem_phase1a/postgres_store.py
- app/sem_phase1a/router.py
- app/sem_phase1a/service.py
- app/sem_phase1a/store.py
- docs/sem-phase1a/HANDOFF_INDEX.md
- docs/sem-phase1a/README.md
- frontend/package.json
- frontend/scripts/test-sem-shadow.mjs
- frontend/src/App.vue
- frontend/src/router/index.js
- frontend/src/router/shadowRoutes.js
- frontend/src/views/onboarding/ShadowPlanningView.vue
- frontend/src/views/onboarding/shadowPlanning.js
- tests/sem_phase1a_main_fixture.py
- tests/sem_phase1a_management_checks.py
- tests/test_sem_phase1a_slice5.py
- tests/test_sem_phase1a_slice6.py

外部交付文件：PLAN.md、改前逐字节PLAN.v12.md、PHASE1A_SLICE6_HANDOFF.md、逐步追加status15.md。所有中文文件UTF-8。PLAN历史完整保留；v12 SHA-256=9cac329bb6d1273f5149dc8b73a1930f29a283f7bbce61c9c69e9fb66e033fe2。

## 验证结果

| 检查 | 实际结果 |
| --- | --- |
| 完整phase0/1a/slice2–6/迁移 | 752 passed、5 skipped；之后新增1项多图部分失败回滚 |
| 受保护本地全库 | 2710 passed、47 skipped、零失败；收集早于最后新增1项，不虚报2711次全库执行 |
| 最终本刀新测 | 14 passed、1 skipped，包含新增多图回滚、条件写/hash/限量/故障与SQLite并发保护 |
| 前端 | build含六路由×三角色真实SFC SSR与表单/按钮/限额/API/时区/授权刷新故障契约，PASS；verify:sem-build、旧chunk恢复/请求取消PASS |
| 远端全库 | 本head CI 2734 passed、24 skipped；前置原生竞态11 passed零skip |
| 必需CI | pytest、SEM task native database contracts、sem-foundation-contracts、sem-frontend-build、Dependencies/OSV均SUCCESS；Deploy SEM frontend only=SKIPPED |
| 安全差分 | git diff --check与暂存差分检查PASS；.github、app/config.py、app/main.py、app/security/auth.py、app/baidu及全部迁移相对基线零差异 |

所有本地Python检查沿用TEMP受保护启动器，禁止真实.env/网络，用已有CI合成配置；没有启动生产服务或调度器。本机原生PG skip不算通过，CI证据如下。

[CI run 40998904709](https://github.com/DoraHai/ai_sni/actions/runs/40998904709)，[pytest job 123878435538](https://github.com/DoraHai/ai_sni/actions/runs/40998904709/job/123878435538)。checkout临时merge=132d421491708176a5fd8c7e3c8c70d588e13e82，日志明确由b06dd187587f33d7528c4f2f818900a8300b6adf合入e6519f5b37d06f24a2c5a7013860f981106f5eff（GitHub临时检查提交，不是本轮执行合并）。2026-10-30T03:44:29.7488677Z出现SLICE6_LIST_NATIVE_PG_EXECUTED: exact account + metadata + pagination PASS；03:44:30.1933032Z出现SLICE6_NATIVE_PG_EXECUTED: last grant + usable advisor + concurrent revoke PASS。既有slice4/5原生标记均PASS，证明原生PG实际执行非skip。03:44:42.2951469Z全库2734 passed/24 skipped。远端前端job 123878435725确认本head临时merge、SSR/功能契约和构建验证均PASS。

## OSS 封存

仅上传诊断文档至oss://snipers-video-transfer/diag-20261029/sem-phase1a-slice6/，不访问生产附件桶。PLAN/PLAN.v12/此交接/仓库README/索引及status15均使用ossutil --retry-times 3上传和下载，回读SHA-256逐份一致后才报告DONE；最终hash见status15逐步记录及SHA256_MANIFEST.json，status自身hash独立记录以免自引用。具体封存结果以本轮status15末行和工具回读输出为准，本段不提前宣称成功。

## 修复轮19 验证结果

- 完整 phase0/1a/slice2–6 与迁移：753 passed / 5 skipped。
- 受保护全库 tests：2711 passed / 47 skipped，没有失败；沿用既有 TEMP 启动器，真实 .env/网络被禁止。PG 本机 skip 不能作为原生通过，仍以新 head CI 日志确认。
- 前端 build（包含新增保护错误回归、六路由×三角色真实SFC SSR）、verify:sem-build、chunk恢复、身份请求取消全部通过。新增测试最后仅清除无效的行快照断言并补精确请求scope断言，test:sem-shadow 再跑通过；运行代码与已验证构建一致。
- 相对 e6519f5b 的 CI/config/main/auth/百度/迁移受限路径零差异，git diff --check 与暂存检查通过。三份文档工作树/暂存 Git blob/外部副本逐字节核验；PLAN.v12 原始哈希不变。
- 准备普通 commit/push 至原 slice6 分支与 Draft PR #824；本轮新 head CI 尚待验证，不以历史绿检查代替。最终文档提交的完整 CI、原生PG标记与 OSS 回读哈希另存 REVIEW19_SHA256_MANIFEST.json。

# SEO-12 本机真实迁移与 API 联调交接

2026-10-07。仅限用户提供的专用空测试库，未连接生产、未推送部署、未执行真实供应商或站外发布。数据库写入、撤权时点与清理由 SEO 窗口负责，工作台只经本机 API 操作。

## 当前可用环境

- 后端 `http://127.0.0.1:8031`；`GET /health/seo` 实测200，schema=ok，revision=`0105_seo_content_confirmations`。运行文件为 `scripts/seo_local_acceptance.py serve`，实际加载原 `app.seo_main` 的业务路由和健康检查。
- 专用数据库 `127.0.0.1:55432/seo_workflow_test`，schema=`public`，普通 `seo_workflow_tester`。不得复用这些ID到生产；这里的tenant/site=1是本轮新造的合成客户，不是生产诺德。
- 主客户/站点 `tenant_id=1, site_id=1`；跨租户负例 `tenant_id=2, site_id=2`。客户user=1、已分配顾问user=2、外客户user=3、未分配顾问user=4。客户仅SEO view权限，可走真实客户确认入口；顾问有SEO edit和站点assignment，无超级管理员权限。
- 草稿content=1（drafting，keyword=1），第二稿content=2（ready、version=2、待客户/顾问准确确认），撤权检查专用第三稿content=3（ready、未发布）。任务task=1对应content=2，阶段已通过真实advance接到待确认；fact=1、page=1。发布链接使用 `https://seo12-primary.invalid/fixture/2`，只是合成发布事实，绝不表示公网已发布。
- 计划所有周期与自动AI默认false；上月日期使用2026-09，没有种子流量/点击或冻结月报，缺数据按缺数据呈现，不假填0/搜索提升。页面没有自动抓取结果，任务不能凭发布登记变成已完成。

凭据只在 `C:/Users/Administrator/.secrets/seo12-local/identities.json`。前端配置用 `export-ui` 输出的 `%TEMP%/seo12-ui-<run_id>/ui12-config.json`，目录ACL限定当前Windows用户及SYSTEM；路径保存在同生命周期目录的manifest.json中。不打印这两个JSON的内容，不上传Git。前端配置只有合成顾问/客户密码，没有数据库密码或JWT签名密钥。

## 真实身份与外部调用边界

- 登录、密码校验、JWT签发、当前User/Role读取、tenant/site校验、业务权限和assignment全部用真正依赖，没有把auth替换成固定超管。
- SEO分支的旧auth路由缺 `/auth/modules`，`/auth/tenants`也没有module筛选。`scripts/seo_local_auth.py` 在**本地宿主**提供共享工作台所需的只读目录桥，复用真正require_auth/get_session、TenantModule、module_is_available及list_module_tenants，读取实际PG中的开通/角色/租户数据。SEO模块口径对照cockpit-foundation现有共享auth实现；未修改生产auth.py。此桥的联调通过不等于共享认证网关部署或完整SEM身份上下文验收。
- 设置完全使用显式本地值，`_env_file=None`，不读取应用.env；DeepSeek/DashScope/站长工具等继承环境密钥不生效，API Key入口关闭。仅保留指定测试库连接。
- `SEO_SCHEDULER_ENABLED=false`、rank调度false、`SEO_EXTERNAL_ACTIONS_ENABLED=false`、page capture=false。首次生命周期之前安装进程网络审计钩子，禁止非指定PG地址的socket连接、外部DNS和浏览器/子进程启动；Uvicorn只绑定127.0.0.1，不开reload/multiworker。
- 允许：认证读取/登录、SEO读取、稿件PATCH/提审/审核、准确确认/退回、计划PUT与明确创建执行链、人工登记/回填、内容链advance。这些仍走真实权限与版本门禁。
- 禁用：AI生成、网站抓取、真实发布/重试、外部账号连接等未列入本地白名单的写操作，返回403 `local_acceptance_action_disabled`。网站诊断advance可能触发抓取，未开放；完整网页证据完成链、AI固定响应/失败适配、冻结报告生成不在本次已运行范围。
- 人工登记成功仅在专用库保存测试事实；页面核验因capture关闭应明确not_queued/capture_disabled，不能报告真实页面证据或任务done。

## 真实迁移验证结果

原Alembic链122个revision、6个合并节点，唯一head=0105。未使用create_all或stamp。

1. 新连接核验指定实例/库/普通角色、public USAGE/CREATE=true、所有用户表/函数/自定义类型为空；只有原plpgsql扩展。
2. 原样运行所有历史迁移至0104；插入真实外键关联的合成客户、角色、用户、模块、站点、关键词、资料、页面和稿件。
3. 原样升0105。首次脚本误把驱动返回的PG内部char字节与字符串比较，导致外键计数失败及基线筛选为空。没有将这次报为通过；修正为catalog显式`::text`，增加“基线必须非空且有稿件”的硬门禁。
4. 确认两张新表均为空后，仅真实downgrade0105→0104，再记录**102张既有表的行数及数据SHA256**，重新upgrade0104→0105；所有旧表指纹保持一致。
5. 核对两张新表的8条真实外键及CASCADE/RESTRICT/SET NULL语义、CHECK/UNIQUE约束。10个实际事务探针验证有效插入、错误版本/决定/actor mode、错误租户/站点/内容/用户引用及重复顾问分配；探针全部rollback。之后新增唯一活动顾问分配供联调使用，未预造客户确认。
6. 当前清单：105张表（含alembic_version）、97条序列、375个索引、2个函数，全部public且属主为测试账号；保留原plpgsql扩展。保留对象用于UI联调，不提前清空。

本地生命周期证据：`C:/Users/Administrator/.secrets/seo12-local/manifest.json`（仅目标/对象/指纹/合成ID，不含数据库密码）；`api-smoke.json`、`session-catalog-smoke.json`记录实际HTTP结果。数据库凭据仅从另一个既有受限env读入内存，没有复制。

原有十项并发PG验收独立保留。本次不是压力测试、完整历史数据升级覆盖、真实供应商/平台或线上端到端验收。

## 启动与协作

当前生命周期已迁移完成，**不要再次prepare或migrate，不要重放已完成的UI业务脚本**。代码与数据由SEO窗口管理，前端配置需在本地提交后export-ui以记录正确backend_commit。

项目Python：`D:/SNIPERS国内版/ai_sni/.venv/Scripts/python.exe`。真实Pillow12.3.0/python-docx1.2.0/openpyxl3.1.5及依赖安装到 `%TEMP%/seo12-runtime-deps`，无全局安装或导入桩；这不等于所有渲染用例已跑。

```powershell
$env:PYTHONPATH="$env:TEMP\seo12-runtime-deps"
& 'D:\SNIPERS国内版\ai_sni\.venv\Scripts\python.exe' scripts/seo_local_acceptance.py serve
```

`prepare`仅新建受限生命周期和随机测试密码；`migrate`只允许全空库且真实迁移源码哈希未变；`seed-ui`通过实际登录/业务API准备第二稿与任务，`seed-revocation`仅SEO创建第三稿再经实际内审API到ready。重复运行已有seed只返回已记录ID，不覆盖浏览器修改。

工作台最短workflow可使用content1/2和task1；撤权模式使用content3。**撤权尚未执行**：工作台先完成workflow并明确请求同步点，SEO再运行 `advisor-revoke`，前端只读验证后SEO运行 `advisor-restore`。CLI仅更新本轮已记录tenant/site/advisor的唯一assignment，记录时间，不提供生产测试控制API。

## 停止与清理

服务在SEO持有的本机进程中运行。优先在该终端Ctrl+C；若需按PID停止，先用Get-NetTCPConnection核对8031监听者，再核对该进程命令为本工作树的seo_local_acceptance.py serve，不能仅凭旧PID杀进程。

全部UI联调完成且允许释放环境后：停止服务和UI写入，运行 `cleanup-plan`。该命令重新核对目标、对象清单及所有权，生成受限目录的cleanup-review.json与cleanup-review.sql，**仅生成、不自动执行**。由SEO复核后在同一专用库执行：先去本轮表之间的外键，再RESTRICT删除本轮表、剩余序列/函数/类型；不DROP DATABASE、不删public、不删扩展，不用CASCADE，不改权限。清单不同或出现非本轮/非测试角色对象则停止。

结束后核对用户对象恢复为空、原扩展/schema/角色保留；删除本轮生成的浏览器配置及合成身份密钥文件仅限上述已核对的本轮目录，原数据库凭据文件保持原样。当前尚未执行清理，数据保留供UI12接续。

## UI12 人工登记故障修复（2026-10-08）

浏览器给 content2 的人工登记提交 `2026-10-08T00:01:00+08:00`，asyncpg 拒绝向无时区字段写入 aware datetime，返回500。只读核对确认这次事务未提交：tenant/site=1/1 下发布、尝试、抓取记录均为0；content1=drafting/v3，content2=ready/v2，content3=ready/v1，三者均无发布地址/时间；content2/v2 的批准仍在。没有重置或重放浏览器业务。

两条人工发布入口统一按 UTC 无时区值存储，响应仍为显式 UTC；上述输入对应 `2026-10-07T16:01:00Z`。未带时区的历史输入继续视为UTC，未传时间继续使用服务器当前UTC。真实PG回归还发现回填提交后 `updated_at` 的异步隐式加载错误，补上显式 refresh，避免提交成功却序列化500。

验证：先在随机隔离schema复现原始asyncpg报错，再运行 `test_seo_workflow_postgres.py`、`test_seo_publication_workbench_contract.py`、`test_seo_distribution.py`，**93 passed、0 skipped**。其中新增10个真实PG时间用例覆盖两个入口的正/负时差、Z、无时区、缺省值；原PG并发与权限门禁一起通过。测试schema已自行清理，public内UI状态保留。

接续只从content2当前版本/哈希读取后登记一次开始；不要从头重跑workflow，不修改content1的v3，不撤销顾问分配。登记成功仅为合成发布事实；外部采集/发布继续禁用，不代表页面核验或真实平台验收通过。顾问撤权仍等待前端完成正常路径后的同步点。

### 撤权及断点接续验收结果

2026-10-08，前端完成撤权只读验证后，SEO已将本轮 user2、tenant/site=1/1 的唯一assignment恢复为 `active=true`，只读数据库核对通过。撤权报告：`C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui12-scenarios-ibkVHy/report.json`。现保持恢复态。

随后前端只接续先前失败的登记和任务推进，没有重放改稿/确认。报告 `C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui12-scenarios-3xK0Hj/report.json` 的实际内容及SEO只读数据库结果一致：

- content2=v2/published；唯一发布记录 **id=1**、source_version=2，地址为合成 `.invalid` 地址。发布时间存储为UTC `2026-10-07 16:01:00`。
- page_verification=`not_queued`，reason=`capture_disabled`，capture_id=null；抓取记录0条。
- task1=`in_progress`，phase=**`page_evidence_needs_attention`**，blocker=`capture_disabled`，completion_evidence=null，关联publication_id=1。未被误标为done。
- 报告 result=passed，browserErrors=[]、externalOrigins=[]，backendCommit=`f97be7800a934c0d19954270e467b79c6318b324`。

协作转述曾写publication_id=2、phase=awaiting_page_evidence；以以上原始报告与数据库值为准。UI业务写入已结束。环境和数据继续保留，释放/清理等待总控安排；未执行真实发布、采集或生产操作。

## UI13 最小维护放行

按前端明确需求，runner仅新增资料POST、资料正整数ID PATCH、关键词正整数ID PATCH三类精确路径；鉴权/模块/站点检查继续使用真实接口。关键词前端表单范围为priority/landing_page，无导入、AI、抓取或真实发布。37项防护单测、15项真实API检查已通过，详见`SEO_AUTOMATION_API.md`的UI13节。

后续空库入口需求另放行关键词POST（前端仅tenant_id/site_id/keyword/priority/landing_page），现共四类维护路径。防护单测38通过，新增关键词6项真实API检查通过；keyword2探针已归档，keyword1不变。仍不开放导入/重命名，不重置原环境。

SEO新增探针资料id=2已停用；原资料1与UI12稿件/发布/任务未改，关键词1的priority/landing_page已恢复原值。用户、assignment及schema未修改。前端可以新建自己的合成资料进行浏览器验收，不需重跑UI12或重置环境。测试记录追加保留，后续由总控安排统一释放。

## UI14 本机追加夹具

显式工具`scripts/seo_local_ui14_seed.py`已经执行一次；批次UI14-20261008，只追加稿件4–63、任务5–49、关键词5–49、新页面2及手工合成截图1/2。40项防护/计划测试和31项真实媒体/分页/确认状态结果检查通过。数据库旧行指纹未变，新增对象及指纹清单在受限目录`ui14-fixtures.json`，API检查在`ui14-readonly-smoke.json`。不要重放，不能把合成审核/截图当真实客户确认或页面证据。

图片PNG位于同受限目录的ui14-media子目录，runner显式使用此目录。capture1成功、capture2失败，稿件4–63均含两张HTML图片，建议从稿件7（ready/pending）只读看稿。runner按生命周期清单阻止新45个任务的advance，原任务1仍保留此前状态。关闭/清理仍由总控安排，必须把本轮媒体文件纳入精确清单，不删除原数据库凭据。

UI14媒体鉴权、来源字段、分页数量和站内沟通最小方案已追加到`SEO_AUTOMATION_API.md`；无新生产路由、无通用URL代理、无人工会话表/迁移。客户顾问沟通尚未接入，不复用私有AI消息。


## UI15 人工消息：本机准备与发布边界（2026-10-08）

候选链为 `0105_seo_content_confirmations → 0106_seo_content_messages`，新增3张表、2个序列、关联索引/约束及一个函数和两条只追加触发器。只有本机固定 `127.0.0.1:55432/seo_workflow_test` 已执行，普通测试角色；104张原业务表全行指纹保持一致，实际 `seo_health` 返回0106/schema=ok。日志及前后指纹保存在既有受限生命周期manifest的ui15_upgrade字段；没有生产变更。

可重复使用的本机命令：`scripts/seo_local_messages.py upgrade`只允许已核验0105、历史迁移源码未变且8031已停止；不支持跳过失败核验、重置或自动回滚。新稿和25条双身份历史使用`seed`准备，消息经真实JWT业务API发送，每条用固定UUID重试核对幂等。消息前后稿件、审核、确认、工单、发布表指纹必须保持一致。之后只在新UI15稿件进行少量浏览器发送；UI12/14数据保留，不重放旧业务。

定向回归276通过、8跳过。消息真实PostgreSQL用例实际执行，覆盖并发8次首发唯一、换文复用键409、客户/顾问、撤权/停用/跨范围/顾问降级view、撤权并发锁、游标分页与单调已读、数据库禁止修改/删除/清空消息、必要结构缺失拒绝、0106旧确认/工单门禁。跳过的是历史迁移用例专用环境，不能算作生产迁移演练完成。

### 已知源代码的0106兼容性

- SEO本轮兼容代码同时接受0105和0106；0106额外检查消息结构，未知及多revision仍拒绝。76ce5920的旧SEO白名单最高0105，数据库到0106后回滚该旧代码会使健康检查失败。白名单最高为0104的更旧SEO包同样不能直接回退：既不认识0106，也不具备本轮针对0105/0106的确认和消息兼容门禁。
- SEM本机已知源 `automation-sem-backend-20261007@4d9c54f834296e155706748685e436859daf34d5`：`app/main.py`的health执行SELECT 1，未设置revision白名单；启动执行生产配置检查和调度器。仅能确认该入口没有0106版本拒绝，不能据此宣称全部业务完成0106验证。
- GEO本机已知源 `geo-workbench-auth-context@f93eac87e37b0e51c20ca923f1cffe023fcc877e`：`app/geo_main.py`的health执行SELECT 1，未设置revision白名单；启动还有任务恢复逻辑。没有启动GEO业务或验证生产运行版本。
- 三个服务实际部署SHA、启动命令及共享数据库revision本轮未读取，必须由管理员在发布准备时对账；上述代码快照不是生产证明。

生产顺序必须是：先单独审核并批准部署兼容0105/0106的SEO代码（数据库仍0105，消息能力503未就绪），核验各服务实际运行版本和回滚包；再单独批准数据库0106迁移及维护窗口，迁后分别检查三服务健康和消息结构。不能由部署SEO隐含授权数据库升级。迁后应用回滚包也须接受0106；不能承诺任意旧包可回滚。不自动执行downgrade，消息表已有数据时降级会丢失历史，需独立数据处置/恢复方案。


UI15最终状态：新增稿64，消息28=25预置+3浏览器，客户游标28/顾问0，assignment已恢复active。原真实写报告TWZN7H末尾有data图标误判，保留failed原件和已完成业务case；前端934a9263的只读复核JM4q6e为passed、无消息写入，后端仍9f303781。两个完整报告路径和脱敏数据库对账路径见`SEO_AUTOMATION_PROGRESS.md`。测试环境继续保留，停止/清理需按本文件既有生命周期流程，不执行生产迁移、不自动降级。

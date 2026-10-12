# 多号通与顾问工作台分发接入：第一阶段本地交付

本档保留第一批验收事实；当前进展与剩余边界见 [第三批交付](DISTRIBUTION_PUBLICATION_HANDOFF_20261011.md)。

此页为第一批交付记录；最新账号节奏、不可变图片和人工核查见 [第二批交付](DISTRIBUTION_SCHEDULING_HANDOFF_20261011.md)。第一批“未接入”描述不能作为最新能力结论。

2026-10-11。本批使用独立工作区与本地提交；没有推送、部署、生产迁移、真实账号登录或平台发布。原多号通程序、安装版和冻结的 SEO/GEO/工作台候选未被覆盖。

## 当前操作流程

1. 超管在“多号通分发接入”创建设备，设备凭证仅展示一次；选择盘点内的客户网站或 GEO 项目，人工确认平台账号归属后绑定。可以查看设备/绑定并分别停用。
2. 顾问从已分配项目列表或当前站内任务页选择项目，明确开始分发。页面读取、保存绑定、进入客户工作台均不会启动 AI 或执行端。
3. 系统只提供当前审核与原生业务门禁通过、符合执行协议的完整渠道稿。顾问预览正文，核对客户、项目、版本和目标账号。
4. 顾问分别授权预检、人工交接，或另行勾选“人工发布”授权。人工发布具有独立 publication grant，不能用预检权限替代。
5. 独立多号通执行宿主明确启动后，通过固定 HTTPS 端点领取授权任务。当前执行器只校验快照/素材并停在人工处理；不打开或操纵真实平台。
6. 人工通过独立宿主受控操作回填 published/unknown/failed。公开链接仅标记“人工报告，页面待核验”；预检完成不会标为发布成功。
7. 顾问可暂停、恢复、结束，并读取任务与操作记录。结束为终态，不能恢复；停用设备/绑定、撤审、改稿、顾问分配变化、过期会阻止继续派发。已派发而结果不确定的任务保留为 unknown，不自动重发。

SEM AI 接管仍关闭。官网修改接口仍为预留。客户工作台继续用于交付查看。

## 已实现的约束

- 每个请求重新核验数据库中的实名用户/角色；顾问还需通过原生模块的服务、项目、当前分配与审核门禁。管理员全局权限与设备凭证分开。通用 API key、匿名与客户只读账号不能控制分发。
- 绑定必须对应客户实际登记的网站/项目；本地账号和平台账号归属冲突被拒绝。既有绑定的外部账号标识不可改写；停用后不会悄悄把旧任务关联到另一个账号。
- 稿件由原生数据库加载，不接受客户端正文或审核声明。创建、派发及回执采用前都重新核验。长稿按 100000 UTF-16 单位上限过滤，不截断已审正文。小红书图文因不可变素材清单尚未接入而拒绝提供稿件。
- 所有写操作带幂等请求号；项目控制带预期版本。对同一平台账号的同稿/同动作，跨设备并发也不能重复派发。unknown 必须人工核查，不能自动换任务号重发。
- 回执绑定客户、项目、设备、账号、平台、稿件版本/摘要和租约；使用 receiptId + sequence 防重复和逆序。仅在数据库事务提交后返回精确 ack。迟到人工链接可保留，但不把已失效任务恢复为成功。
- 项目暂停通过 pausedTaskIds 下发，执行端继续心跳以接收恢复/停用；本机 stop 则停止交换。设备状态、内容、回执与审计在独立 SQLite 持久化；回执在 ack 前保留。
- 每次设备交换最多 100 个活跃任务、200 个授权；每设备活跃任务上限 100。响应控制在 900000 UTF-8 字节内，超额完整任务继续排队。收到本机持久化 ACCEPTED 后只刷新授权，避免反复传输整篇正文并阻塞后续任务。
- 事件/回执表禁止更新或删除；审计不存正文或设备凭证。服务端只保存凭证摘要。浏览器不持久化设备凭证；会话/权限变化清除快照与预览。写操作响应不确定时提示核查，不自动重发。

## 工作区及组装边界

| 组件 | 本地目录/版本 |
| --- | --- |
| 共享协议、broker、路由、顾问/超管 UI | `distribution-control-20261011` / `codex/distribution-control-20261011`，基于工作台冻结版本 `54e411f013ae53aa3d23895f1f50059f904768b8` |
| SEO 原生来源与联调 | `seo-distribution-sources-20261011` / `c1af7ded597752c9dfb63dd920ae9aef5647b21c` |
| GEO 原生来源与联调 | `geo-distribution-source-20261011` / `1732b77ef3dfec8c8b9e7feb080d224f5f6a1297` |
| 独立多号通执行端 | `D:/微信小工具箱项目/wechat-toolbox-distribution-20261011` / `21300b7363ae1c99c9917f5d6188567a9f11e1c9` |

共享候选的工作台基线包含较旧的后端，**不能把此工作树整体作为统一后端部署包**。原生模块适配器分别依赖其当前 models 与门禁，未粗暴合并至旧后端。没有安装适配器时 API 返回 503，不能旁路校验。

模块组装时需要共享 `app/distribution_contract.py`、`app/distribution_control.py`、`app/api/distribution.py`，注册 router；SEO 使用其原生 `app/seo_distribution_sources.py`，GEO 使用其原生 `app/geo/distribution_sources.py`。两个模块已通过 importlib 在各自当前原生 app 中加载同一共享候选完成真实数据库测试；没有替换它们的鉴权/来源方法。

前端改动保持独立工作台入口，并复用既有登录/会话来源。构建产物位于 `customer-workbench/dist/customer-workbench`；多号通独立 Node 宿主位于 `out/distribution`，不依赖原 Electron 入口。生产候选组装仍需选择正确后端基线、审查最小补丁与新增 DDL，然后做部署环境联调，不能以单元测试替代该步骤。

## 验证

| 验证 | 结果与性质 |
| --- | --- |
| 中央 broker + PostgreSQL + HTTPS | 23 项通过；独立合成库、真实 bearer 校验、合成来源；其中 1 项是真实 loopback TLS + 独立 Node 执行器 + 持久化 ack |
| 前端契约回归 | 163 项通过；包括 16 项新增分发契约测试 |
| 分发及顾问/超管浏览器回归 | 7 项通过；构建产物、真实 Edge，API 使用受控合成响应；包含分发 2 项、既有顾问/自动化/超管 5 项 |
| 最终共享候选 + 原生 SEO | 16 项通过；真实 PostgreSQL/JWT/角色/分配/客户确认与来源，未 mock 原生门禁 |
| 最终共享候选 + 原生 GEO | 1 项完整链路通过；真实 PostgreSQL/login/JWT/GEO 门禁，未 mock 原生来源 |
| 原生模块各自组合回归 | SEO 142、GEO 47 项通过（模块窗口报告与证据） |
| 多号通独立端 | 327 项单元测试、构建及 15 组本地 HTTPS/CLI 检查通过（独立窗口报告） |

这些计数有覆盖重叠，不相加作为独立端到端案例数。浏览器测试和 broker 合成来源测试不是生产渠道验收。没有以测试通过推断真实账号登录、平台发布或搜索效果。

中央 PostgreSQL 验证只在 `distribution_test@127.0.0.1:55443/distribution_control_test` 的随机 schema 执行，结束后清理。DDL `scripts/distribution_control_schema.sql` 从未对生产执行，也不由应用自动建表。

本地复验：

```powershell
# 前端，位于本候选 customer-workbench
npm run test:distribution
npm run test:contracts
node --test advisor-browser.test.mjs advisor-automation-browser.test.mjs advisor-automation-v2-browser.test.mjs platform-console-browser.test.mjs

# 后端，先启动上文的独立测试库，使用具有项目依赖的 Python 环境
$env:DISTRIBUTION_TEST_DATABASE_URL='postgresql+asyncpg://distribution_test@127.0.0.1:55443/distribution_control_test'
$env:DISTRIBUTION_NODE_RUNNER='D:/微信小工具箱项目/wechat-toolbox-distribution-20261011/out/distribution/https-runner.mjs'
python -m pytest tests/test_distribution_control_postgres.py tests/test_distribution_https_interop.py -q
```

多号通构建与明确 start/run/stop/shutdown、凭证注入、授权正文查看和人工回填命令详见其 `docs/DISTRIBUTION_HOST.md`。HTTPS fixture 与 Python/JS 摘要示例位于其 `docs/fixtures/distribution-v1.json`。

## 下一阶段

当前可用于内部验证受控交接，尚不能承诺真实自动发布。接下来先实现受控凭证供应器/安全存储与账号登录态核验，再接不可变素材、平台草稿/上传适配，最后使用授权测试账号逐渠道真人验收。自动正式发布需要独立能力开关、单独授权与失败结果核查。

还需补充公开作品内容核验、任务 unknown 的人工核查处置、版本化部署组装、生产审计保留/备份策略与运行告警。第一阶段的人工回填目前仅记录事实，未核验真实作品内容。没有在本批启用这些未验证能力。

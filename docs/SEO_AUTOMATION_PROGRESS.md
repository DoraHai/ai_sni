# SEO 辅助自动化开发进度

基线：`D:/SNIPERS国内版/ai_sni-worktrees/automation-seo-20261007`，分支 `codex/automation-seo-20261007`，起点 `d59d1a2c44ab3b677968eea8ac2ad94a036bbf76`。只改 SEO 模块；客户工作台、SEM、GEO 不在本目录改动。

## 批次索引（2026-10-07）

| 批次 | 本地提交 | 交付重点 |
| --- | --- | --- |
| SEO-01 | `6cd941f5` | 精确版本确认、顾问代确认、0105 迁移源文件与发布门禁 |
| SEO-02 | `bb3f477a` | 服务阶段状态与发布成功后的页面核验接续 |
| SEO-03 | `40c3a153` | 顾问版本化服务计划 |
| SEO-04 | `c5f3a523` | 页面整改任务与重新检查完成证据 |
| SEO-05 | `f19f6a3d` | 逐关键词缺报和过期识别 |
| SEO-06 | `9a892711` | 最新指标序列与月报就绪状态 |
| SEO-07 | `7bf04a05` | 站点自动化暂停与恢复 |
| 收尾修复 | `c536d625` | 核验状态语义、顾问分配并发锁及最终审查 |
| UI-04 契约 | `8ec3dbf0` | 服务计划允许动作、状态口径和0104兼容 |
| SEO-08 | `9c7aa6f8` | 计划驱动的持久化内容辅助执行链 |
| SEO-09 | `f9a22877` | 周期诊断整改、排名异常待办、冻结月报与执行链只读投影 |
| SEO-10 | `c8fa621e` | 顾问显式开启的自动草稿、触发能力、人工登记版本门禁与并发测试包 |
| SEO-11 | `67975f32` | 自动草稿锁定 DeepSeek、目标完成证据与站点总量拆分 |
| SEO-12 | 本批本地提交，见 Git 日志 | 完整真实迁移、合成身份/数据、本机FastAPI与清理运行包 |

以上均为本地提交。当前没有推送、PR、合并、部署或生产迁移。SEO-01–07 完成的是基础契约和局部接续，不是完整 A01–A07 自动化。以下状态按实际执行链重新标注；不能用事实汇总或单点接口代替周期任务运行。

当前剩余项：

- UI12本机浏览器联调暴露的人工发布时间500已定向修复：登记/回填统一UTC存储，回填响应显式刷新数据库更新时间。三组相关测试93通过（含10个新增真实PG时区用例）。撤权只读及恢复后断点接续均已通过：content2/v2关联publication1，task1停在in_progress/page_evidence_needs_attention，blocker=capture_disabled、完成证据为空。原始浏览器报告与只读数据库核对一致，顾问分配已恢复；环境保留待总控安排释放。此结果不包含真实外部采集/发布或生产验收。

- SEO-08–12 已实现本地辅助执行链及可选 DeepSeek 自动草稿，目标交付与全站效果分开；总控十项PG并发/防护验收、SEO-12真实历史迁移及0104有数据基线→0105约束/保留验证均已通过。本机真实API已就绪，工作台浏览器联调待接续；压力测试、其余数据库用例、生产资源授权和外部平台验收仍未完成。网站诊断有每轮10页上限，排名异常首期为百度桌面全国最多200词，报告为冻结 HTML，不称全域/全渠道自动化。
- 工作台依据 `SEO_AUTOMATION_API.md` 完成真实接口适配和联调。
- 单独审核、批准并执行推送、PR、合并、SEO 兼容版部署及 `0105` 数据库迁移。
- 在获准测试客户/站点上配置顾问分配、服务计划和真实数据源，再做真人与外部平台验收。
- 既有 PDF 月报仍按需生成；SEO-09 已新增周期 HTML 报告准备及顾问说明，不自动推送 PDF。
- 站外消息通知尚未实现，等待统一通知通道；SEO 仅返回可读 blocker、任务和待人工接管状态。
- 5 个依赖真实 Pillow/python-docx 的渲染测试文件仍需在完整渲染依赖环境补跑。

## 完整清单

| 能力 | 批次 | 当前状态 | 完成证据/后续 |
| --- | --- | --- | --- |
| SEO-A01 资料与服务计划 | SEO-02/03/07/08/09 | 周期规则本地实现 | 内容、网站、监测、报告周期可显式开启，默认关闭；按站点幂等、暂停、游标恢复 |
| SEO-A02 网站检查与优化 | SEO-02/04/09 | 有界辅助链本地实现 | 周期单页抓取→快照→整改子任务→人工实施→真实复检接续；每轮最多10页，无全站自动发现 |
| SEO-A03 关键词与搜索监测 | SEO-02/05/09 | 固定范围辅助链本地实现 | 百度桌面全国缺报/过期/下降待办及新观测核销，最多200词；采集仍复用原调度，其他引擎/设备待扩展 |
| SEO-A04 内容制作与稿件确认 | SEO-01/08/10 | 可选自动草稿辅助链本地实现 | 默认关闭、顾问显式开启、事实/关键词约束及一次自动生成，人工质量审核和准确版本确认后继续；本批只用假供应商测试 |
| SEO-A05 发布与核验 | SEO-01/02/08 | 首条辅助链本地实现 | 顾问使用既有分发/回填；调度接页面证据，结果不明不重发；自动渠道选择和全渠道交付尚未实现 |
| SEO-A06 数据与报告 | SEO-02/06/09 | 周期 HTML 辅助链本地实现 | 冻结上月报告、缺数说明、准确哈希顾问解释；无自动统计拉取、PDF生成或主动推送 |
| SEO-A07 流程运行 | SEO-01/02/07/08/09 | 四类执行链本地实现 | 持久化、幂等、恢复、暂停、取消、异常接管和只读投影；站外通知及生产验证未完成 |

## SEO-01：版本、确认、代确认与状态接口

关联：SEO-A04、SEO-A05、SEO-A07。

业务决定：客户只确认稿件；顾问可代确认但必须记录真实顾问身份与准确版本；普通稿件不强制提交人与审核人不同；确认不等于发布；客户沉默不视为同意。

本地改动：

- `app/models/seo.py`：新增站点顾问分配与追加式内容确认模型。
- `migrations/versions/20261007_0105_seo_content_confirmations.py`：新增迁移源文件，未执行。
- `app/api/seo.py`：新增交付读取、客户确认/退回、顾问代确认、顾问分配接口；审核支持预期版本；发布、人工回填、材料和重试增加确认门禁；未知发布结果要求明确核对为未发布。
- `app/security/auth.py`：登记工作台内容与顾问分配路径；动作权限仍由端点按 AND 规则和分配记录复核。
- `app/seo_main.py`：允许代码先兼容 0104/0105；0105 增加必要结构检查。
- `docs/SEO_AUTOMATION_API.md`：稳定接口、字段、权限、错误码、版本和上线依赖。

授权依据：

- 客户直接确认：实名账号 + 服务端租户绑定等于目标租户 + `seo.content:view/edit`。
- 顾问代确认：实名账号 + `seo.content:edit` + `seo_site_advisor_assignments` 的目标租户/站点 active 记录。
- `AuthContext.tenant_id=None`、角色字符串、用户名或前端 advisor 标志均不能单独授权代确认。

兼容性：

- 已上线审核接口的 `version_count` 暂为可选；新工作台必须发送。等旧 SEO 内页完成适配后再评审收紧。
- 旧稿件不会自动生成确认记录；新发布动作会被门禁阻止，必须完成真实确认。
- 外部发布状态同步保持可用，避免因确认失效而无法核对已经发生的外部动作。

验证记录：

- `py -3 -m py_compile app/api/seo.py app/models/seo.py app/models/__init__.py app/security/auth.py app/seo_main.py migrations/versions/20261007_0105_seo_content_confirmations.py`：通过。
- 隔离测试使用假数据库 URL、假供应商配置和临时的文档依赖导入桩，没有读取生产 `.env`、真实客户凭据或业务数据。
- `pytest` 定向覆盖内容确认、内容审核、发布/国内平台、发布包/导入、发布一致性、鉴权、健康检查和迁移链：**439 passed, 8 skipped, 1 warning**。跳过项为既有环境相关测试；唯一 warning 为既有 `jieba` 对 `pkg_resources` 的弃用提醒。
- `git diff --check`：通过。

代码审查结论：

- 客户编辑账号不会自动被视为顾问；没有站点顾问分配时不能使用 `advisor_proxy`。已有顾问分配的租户绑定账号也不能选择 `customer_direct` 冒充客户。
- `0104` 阶段通过数据库 revision 判定保持既有发布流程；新确认接口明确返回 schema unavailable。`0105` 才启用确认门禁，避免代码先部署时破坏旧流程。
- 发布请求先做源版本冲突判断，再检查当前版本确认；已发生的外部发布仍允许同步状态。未知结果没有 `manual_check_outcome=not_published` 时拒绝重试。
- 迁移链、生产部署工作流的 Alembic head 检查和 SEO 源文件白名单已同步到 `0105`，但本批没有执行迁移或部署。

提交/发布：SEO-01 已本地提交 `6cd941f529d482ae6741feb64b142cb99d747859`；未推送、未建 PR、未部署、未执行迁移。

下一批：SEO-02 从 A01/A02/A03 的资料与服务计划、网站检查、关键词监测状态接续开始，并继续 A05 发布后页面核验自动接续；不会把 SEO-01 完成写成全部自动化完成。

## SEO-02：服务阶段状态与发布后页面核验接续

关联：SEO-A01、A02、A03、A05、A06、A07。

本地改动：

- 新增只读 `GET /api/v1/seo/workbench/service-status`，按站点汇总品牌资料、目标关键词、优化方向、页面检查/爬取、排名观测与运行、发布页面核验、指标数据和自动运行状态。
- 阶段状态只根据持久化事实计算，返回具体 blockers、观测时间和原始证据接口；GET 不触发采集、AI、发布或任务生成。
- API 发布、人工发布登记、人工完成、同步以及重试五条成功路径在发布事实提交后自动建立页面核验任务；重复请求复用最近记录。
- 页面核验关闭、缺 URL/站点或排队失败会明确返回原因。排队异常不会回滚已经确认的外部发布事实。

验证记录：

- `py -3 -m py_compile app/api/seo.py app/api/seo_page_captures.py app/security/auth.py`：通过。
- 定向测试覆盖发布流程、页面核验 API、工作台证据/状态和静态演示：**129 passed, 1 warning**。唯一 warning 为既有 `jieba` 对 `pkg_resources` 的弃用提醒。
- 扩大到 60 个 SEO 测试文件：**1249 passed, 102 skipped, 6 failed, 1 warning**。6 个失败全部位于月报图片、发布清单图片和 TDK Word 导出，原因是本机隔离导入桩仅支持导入、没有 Pillow `Image.new/open` 和 python-docx `Document.styles` 的真实渲染能力；本批没有改动这些模块。另 2 个依赖真实 Pillow 的文件在收集阶段同样无法由该导入桩运行。没有把这些环境失败记作通过。
- `git diff --check`：通过。

提交/发布：本段为提交前历史快照；SEO-02 最终已本地提交 `bb3f477a`。未推送、未部署、未执行迁移或真实采集。

下一批：补服务计划写入契约与权限、诊断问题转人工实施/复检任务、排名缺报/异常待办，以及周期报告接续。A01-A07 仍未全部完成。

## SEO-03：顾问服务计划

关联：SEO-A01、SEO-A07。

本地改动：

- 新增 `GET/PUT /api/v1/seo/workbench/service-plan`，保存站点优化方向、内容主题、服务备注和 active/paused 状态。
- 服务计划采用 `expected_revision` 乐观锁，服务端记录真实更新人和更新时间；不会复制关键词、品牌资产或声称已执行调度。
- 写入仅允许实名、同时具备内容/网站编辑权限且在 0105 顾问分配表中有当前站点 active 记录的顾问。全租户权限、前端角色或客户编辑权限不能单独写入。

验证记录：

- 服务计划、确认权限、工作台状态和静态契约定向测试：**76 passed, 1 warning**。
- Python 编译和 `git diff --check`：通过。

提交/发布：本段为提交前历史快照；SEO-03 最终已本地提交 `40c3a153`。未推送、未部署、未执行迁移或真实采集。

下一批：诊断问题转人工实施/复检任务和排名缺报/异常待办。

## SEO-04：页面整改任务与复检证据

关联：SEO-A02、SEO-A07。

本地改动：

- 通用 SEO 任务新增 `page_remediation`，创建时校验当前租户/站点的真实 `page_id`，并由服务端固化问题基线。
- 指标快照新增 `seo.site.healthy_page_count`，口径为最近检查状态 `healthy/verified` 的页面数。
- 页面整改任务只有在任务创建后重新检查、页面无问题且健康页面数真实增加时才能完成；完成证据记录页面、复检时间、HTTP 状态和审计分数。

验证记录：

- 页面任务、指标、工作台任务可见性与确认接口联合定向测试：**59 passed, 3 skipped, 1 warning**。
- Python 编译和 `git diff --check`：通过。

提交/发布：本段为提交前历史快照；SEO-04 最终已本地提交 `c5f3a523`。未推送、未部署、未执行迁移、抓取或网站修改。

下一批：排名缺报/异常待办和周期报告接续。

## SEO-05：排名覆盖缺报与过期识别

关联：SEO-A03、SEO-A07。

本地改动：

- 服务状态按 active 关键词逐一检查最近自有域名排名观测，区分从未采集和已经过期；复用百度排名新鲜度配置，不因历史上有旧数据就显示 ready。
- 返回缺报/过期数量和最多 100 个关键词 ID，超出时明确 `coverage_truncated`。最近排名运行 failed/partial 仍单独保留为运行异常。
- 显著排名下降继续复用既有 `create_rank_drop_content_tasks_safely`，生成“自动建议、勿发布”的内容任务，不新增重复告警系统。

验证记录：

- 排名覆盖、页面任务、服务计划和工作台状态联合定向测试：**59 passed, 3 skipped, 1 warning**。
- Python 编译和 `git diff --check`：通过。

提交/发布：本段为提交前历史快照；SEO-05 最终已本地提交 `f19f6a3d`。未推送、未部署、未执行真实排名采集。

下一批：周期报告接续、运行提醒/暂停恢复语义和最终全量审查。

## SEO-06：指标与月报就绪状态

关联：SEO-A06、SEO-A07。

本地改动：

- 数据与报告阶段改为按 `metric_type + dimension + source` 仅看最新观测，旧的成功/失败记录不再污染当前状态。
- 最新指标序列非 available 时返回 `latest_metric_observations_incomplete`，并给出当前状态分布、GSC 配置事实和现有站点月报入口。
- 月报仍由用户按现有只读接口生成；本批没有自动生成 PDF、写客户确认或启动外部统计采集。

验证记录：

- 工作台状态、站点统计和月报 API 定向测试：**30 passed, 1 warning**。
- Python 编译和 `git diff --check`：通过。

提交/发布：本段为提交前历史快照；SEO-06 最终已本地提交 `9a892711`。未推送、未部署、未采集生产统计数据。

下一批：运行提醒/暂停恢复语义和最终全量审查。

## SEO-07：站点自动化暂停与恢复

关联：SEO-A01、SEO-A03、SEO-A06、SEO-A07。

本地改动：

- 服务计划 `paused` 会阻止新的手工排名/竞品/外链采集，并在后台排名、竞品、外链和驾驶舱指标调度选取时排除该站点。
- 恢复 `active` 后重新进入后续调度候选；暂停期间不删除任务、证据和历史，也不补造运行成功。
- 服务状态明确返回 `service_plan_status` 和 `service_plan_paused` blocker。已经入队/运行的任务保持原有持久化结果，避免中途取消外部请求造成未知结果。

验证记录：

- 手工自动化、排名/监测调度、自动运行、指标任务和工作台状态定向测试：**108 passed, 3 skipped, 1 warning**。
- Python 编译和 `git diff --check`：通过。

提交/发布：本段为提交前历史快照；SEO-07 最终已本地提交 `7bf04a05`。未推送、未部署、未执行生产调度。

下一步：最终联合回归、代码审查和完成度复核；主动通知依赖统一通知通道，不在 SEO 内另建消息系统。

## 最终联合回归与代码审查

- 排除 5 个明确需要真实 Pillow/python-docx 渲染、而本机隔离导入桩无法执行的文件后，全部 SEO 测试：**1245 passed, 102 skipped, 0 failed, 1 warning**。
- 另一次包含渲染模块的扩展运行：**1249 passed, 102 skipped, 6 failed**；6 项均是隔离导入桩缺少 `Image.new/open` 或 `Document.styles`，本批未改动相关渲染代码，未把这些环境失败记为通过。
- 最终权限审查：客户确认、顾问代确认、服务计划写入均使用服务端身份和分配记录；服务计划写入锁定顾问分配，管理员并发撤销不会与写入穿透。
- 最终事务审查：外部发布事实先持久化，再单独排页面核验；核验排队失败不覆盖真实发布结果。未知发布结果仍禁止盲重试。
- 最终口径审查：发布成功、页面核验、搜索效果和任务完成保持独立；页面核验按发布记录去重，指标状态只看每个来源最新观测，排名覆盖按启用关键词逐一计算。
- 最终范围审查：未推送、未建 PR、未部署、未执行 0105 迁移、未读取生产凭据、未运行真实客户采集或发布。

## UI-04 联调契约补充

- 服务计划 GET 新增服务端计算的 `allowed_actions.update_service_plan` 和权限依据；判断复用真实用户、内容/网站双 edit 权限及 active 站点顾问分配。PUT 仍独立重新校验全部条件和 revision。
- 服务状态新增 `semantics`，明确 phase state 仅是事实就绪度，不是任务完成；补充 content delivery、任务台账和发布尝试等真实证据入口，不补造负责人、时间线或回执。
- 0104 兼容期 content delivery 明确返回 `confirmation.status=unavailable` 与 `workflow_status=confirmation_unavailable`，确认及开始发布动作均为 false。
- 定向测试：**36 passed, 1 warning**；Python 编译和 `git diff --check` 通过。
- 本补充仅为本地代码和契约，未推送、未部署、未迁移。

## SEO-08：首条持久化内容服务执行链

关联：SEO-A01、A04、A05、A07。分支 `codex/automation-seo-20261007`。老虎站点登录/采集准备单独记录，不是本地自动化开发的阻塞条件，也不计入本链完成证据。

实现文件与行为：

- `app/seo_content_workflow.py`：复用 SeoTask、SeoContentAsset、确认、发布和页面采集。计划周期或明确请求实际创建选题稿件及工作项；顾问制作/审核、准确版本确认后，跟进既有分发记录，人工回填后接页面证据。此模块不调用 AI 或发布供应商。
- `app/api/seo.py`：`POST /workbench/service-plan/run`（UUID 幂等、expected_revision）、`POST /workbench/content-workflows/{id}/advance`（可明确选择发布记录）；实名、双 edit 权限、当前站点真实顾问分配和模块/站点状态都由后端复核。服务计划增加默认关闭的周期选项，旧客户端省略时保留旧值及游标。
- `app/seo_scheduler.py`：每分钟处理内容链。按站点独立事务；按 ID 分页遍历，单站点故障不阻断后续；0104/未知/多个数据库 revision 不进入执行链。只有实际开启周期且有选题、优化方向、有效顾问分配才创建新周期。
- `app/api/seo_cockpit.py`、`app/security/auth.py`：新 action_type 可按内容权限读取；通用 PATCH 禁止人工修改该链状态/负责人；取消保留已有事实，专用推进接口也不能给已结束任务改状态。读取不会启动工作。
- `app/api/seo_page_captures.py`：领取 pending 采集使用行锁；执行前检查计划暂停；复用记录还需同一个 URL。流程从重启前 pending 恢复派发，运行超时/供应商失败交人工复检，不循环重试。
- `app/api/seo.py` 的发布后排队错误处理：缓存发布 ID，避免 rollback 后读取失效 ORM 对象；rollback 本身失败也不会覆盖已提交的发布事实。
- `scripts/verify_seo_release.py`：登记新 SEO 源码和定向测试白名单。
- `docs/SEO_AUTOMATION_API.md`：稳定请求/示例、错误码、人工入口、状态和完成语义；本文件修正旧 A01–A07 状态，保留历史批次记录。

关键约束与审查：

- 同站点通过站点行锁串行预留，稿件、任务、游标一个事务；跨请求重试、已完成/取消任务的原 UUID 重放不另建。每站点最多一个未结束链，错过多期不集中补建。
- 定时触发明确记录系统来源，不冒充顾问点击；`assignment_advisor_id` 是创建依据，不是当前个人负责人，运行时重新核查 active 分配。
- 内审、准确版本确认、平台发布、自动页面证据分别判断。多条当前版本发布记录由顾问选择一条；其他平台不被自动算作完成。
- failed/publishing/未知发布结果停在核对阶段；执行链没有发布、重发或重试供应商调用。渠道未选时创建人工待办，不伪造已配置账号或成功发布。
- 完成需新发布事实、同租户/站点/发布地址且发布时间之后的自动页面证据，以及真实站点近7天发布篇数增长。手工截图、过期确认、跨客户证据、指标未增长都不能 done；页面证据不代表页面 SEO 全部通过、收录或搜索效果增长。
- 两天逾期仅是内部待办字段，`notification_sent=false`；没有发送任何站外通知。阶段历史保留最近100条并明确截断。

验证：

- 隔离配置：假数据库 URL/供应商配置，SQLite 临时持久化数据库与假截图供应商；没有读取生产 `.env`、客户凭据、Cookie 或执行真实采集/发布。
- 首轮4文件：**78 passed**。扩展7文件曾发现一项旧任务类型枚举断言未包含 content_delivery，已修正，未把失败记作通过。
- 最终11文件定向回归：`python -m pytest tests/test_seo_content_workflow.py tests/test_seo_content_confirmations.py tests/test_seo_page_capture_api.py tests/test_seo_scheduler.py tests/test_seo_cockpit.py tests/test_seo_cockpit_auth.py tests/test_seo_workbench_publication_page_evidence.py tests/test_seo_distribution.py tests/test_seo_domestic_distribution.py tests/test_seo_distribution_package.py tests/test_seo_distribution_import.py -q`：**232 passed, 3 skipped, 1 warning**。跳过为既有 PostgreSQL 环境测试；warning 为既有 jieba/pkg_resources 弃用提醒。
- 新测试包含真实 SQL 回滚与跨 session 幂等、周期开关/到期/暂停恢复、真实既有 manual_complete 接口回填、HTTP 后台派发丢失后的恢复、超时/失败不重发、版本修改/退回再确认、多平台选择、只读无写、权限/租户隔离及断开连接后的发布事实保留。
- SQLite 不验证 PostgreSQL 行锁的并发语义；真实 PostgreSQL 并发压力与前端宿主联调仍未验收。真实平台发布、生产采集亦未验收。
- Python 编译、`git diff --check`：通过。

提交状态：随本批本地提交 `feat(seo): run durable assisted content workflows` 保存；准确 SHA 以 Git 日志为准。未推送、未建 PR、未合并、未部署、未执行迁移。

下一批：网站诊断到整改复检的周期执行链，再接监测异常工作项及周期报告。自动 AI 生成/自动选择发布渠道和统一站外通知仍是明确缺口；本批不是全部 SEO 自动化交付完成。

## SEO-09：周期网站诊断、排名异常、报告准备及工作台读取

关联：SEO-A01/A02/A03/A06/A07，分支仍为 `codex/automation-seo-20261007`。SEO-08 内容稿件制作、内审、渠道操作仍是正式人工阶段，未把它改称全自动生成发布。

实际实现：

- `app/seo_service_workflows.py`：三种持久化服务任务，按明确请求或服务计划周期创建；每种类型每站点最多一条未结束链。复用现有 SeoTask，不新增迁移或编排平台。
- 网站：按最久未检查页面选择1–10页，一次派发一页，复用 `collect_page_snapshot/save_page_snapshot` 保存实际 SeoCrawlRun/SeoPageSnapshot；发现问题自动生成/复用 page_remediation 子任务，人工实施和原有 audit 复检后，核实真实指标证据并接续。
- 监测：对百度桌面全国自有域名最多200个启用关键词创建具体缺报、过期、下降至少5位待办。只消费既有排名观测，新的正确范围观测及恢复条件满足后自动结束。没有异常是明确 cancelled/no_actionable_issues 空操作记录，不冒充 done；缺词或超限明确阻塞该周期。
- 报告：生成上一完整北京时间自然月的 HTML 月报，保存 SHA256、发布/统计行引用、缺数说明；顾问针对准确哈希填写业务说明后结束。无需客户签收；统计缺失不补零，不调用统计供应商、不内嵌截图、不生成/推送 PDF。超过200条月度发布记录明确阻塞，不截断后冒充完整报告。
- `app/api/seo_service_workflows.py`：只读列表、详情和已存报告下载；返回全量分页数、真实阶段/处理角色/周期阻塞、证据链接、服务端 allowed_actions；GET 不推进、生成、抓取、通知或发布。另提供周期触发、推进/失败单页重试、准确报告说明及取消接口。
- `app/api/seo.py`：服务计划增加默认关闭的网站/监测/报告周期选项；旧客户端省略新字段时保留现值，开启监测额外要求关键词编辑权限。
- `app/seo_cockpit_metrics.py`：增加真实页面观测数、固定范围排名观测数及已生成报告数；维持共享快照/trend_7d 结构及一句话口径。计数增长不单独构成问题解决，执行链另外核查每个目标证据。
- `app/api/seo_cockpit.py`、`app/security/auth.py`、`app/seo_scheduler.py` 和 SEO 发布白名单：登记类型/权限/调度；禁止通用 PATCH 人工勾选执行链 done。
- `docs/SEO_AUTOMATION_API.md`：工作台读取路径、字段示例、允许动作、权限/分页/日期/错误、自动与人工边界及源码函数位置。

定向审查与修复：

- 锁顺序为顾问分配→站点→任务；采集调用前先持久化单页 claim，网络请求期间不持有事务锁。同站点已有 running 页时不再领取第二页。
- 重启后 queued 可继续；running 超过两分钟转失败待明确重试。失败结果不循环自动请求，保留已经保存的失败快照。取消或失去归属后不写入成功结果。
- 执行前验证站点域名与归属、模块启用及当前顾问分配；复用 crawl_urls 日配额。较新的人工复检已写入时，旧的周期响应不能覆盖它。
- 缺关键词/关键词超限只记录对应周期阻塞，不回滚同站点网站和报告工作；暂停/恢复保留游标、已存报告和历史。明确触发也更新周期游标，避免完成后立即重复生成同月报告。
- 只读能力计算重新核查当前服务端权限，排名链额外关键词权限；未授权记录从 total 中排除。报告列表不返回 HTML，下载有 no-store、附件下载、nosniff、sandbox CSP；未选择或读取统计凭据字段。
- 报告说明绑定准确哈希；修改后端统计数据不会静默重写冻结报告。任务完成、审核、发布、页面检查、搜索效果继续分别表述。

验证记录：

- 首轮新增测试：11 passed、1 failed；失败为隔离夹具误用 description 字段，已改为模型实际 meta_description 后重跑。
- 扩展定向测试：239 passed、3 skipped；最终加入真实 HTTP 契约、配额、默认关闭、手动/定时去重与报告暂停恢复后，12文件回归：**292 passed, 3 skipped, 1 warning**。
- 命令：`python -m pytest tests/test_seo_service_workflows.py tests/test_seo_content_workflow.py tests/test_seo_content_confirmations.py tests/test_seo_scheduler.py tests/test_seo_cockpit.py tests/test_seo_cockpit_auth.py tests/test_seo_workbench_publication_page_evidence.py tests/test_seo_monthly_report_api.py tests/test_seo_site_analytics.py tests/test_seo_single_page_audit.py tests/test_seo_demo_runtime.py tests/test_seo_release_consistency.py -q`。
- 使用隔离 SQLite 持久化数据库、假网页采集器、假配置和 FastAPI TestClient；没有真实采集/发布或读取生产凭据。三项跳过为既有 PostgreSQL 环境测试；warning 为既有 jieba/pkg_resources 弃用提醒。
- PostgreSQL 并发行锁压力、真人网站实施/复检、真实排名供应商、前端 DOM 挂载及生产配置仍未验收；SQLite 回滚/重启测试不替代这些验证。
- 最后一项审查收紧：无效排名0不能被当成下降后的恢复。修复后的新周期模块再跑 **23 passed, 1 warning**；Python 编译和 `git diff --check` 通过。

本批提交：本地 `feat(seo): connect diagnosis monitoring and report cycles`，准确 SHA 以 Git 日志为准；未推送、PR、合并、部署、生产迁移。工作台应读取本地接口契约再挂载，不能认为生产已可调用。

后续：工作台挂载四类执行链、PostgreSQL并发验证、报告截图/PDF自动化及统一通知通道；内容自动AI制作/自动选渠道和真实业务授权仍是单独缺口。周期网站全站发现、更多搜索引擎/设备的待办亦不在本批已实现范围。

## SEO-10：自动草稿与显式触发能力

开始实现前核对：已有 `POST /content-ai/assist`、DeepSeek 模块的供应商路由、日配额及 SeoAiOperation 持久化领取/结果/退款；已有按客户/站点隔离的 SeoQaFact 资料库。复用这些能力，不新增生成平台或另一套生成 API。供应商模块目前优先使用已配置的 DashScope，再回退 DeepSeek；本批不改变路由、不读取生产凭据。

最小设计：

- 服务计划增加默认关闭的 `content_ai_enabled`、顾问选择的 `content_ai_fact_ids`（最多20）和 `content_ai_keyword_ids`（最多5）；显式开启记录真实授权顾问，旧客户端省略时保留原值。仅使用同站点有效事实及启用关键词，材料无出处/过期/缺失转人工。
- 现有内容链调度器接入一次自动草稿领取；先持久化任务领取和输入版本，再调用既有 assist。领取后重启只查既有 operation 结果，不盲目再次请求供应商；失败或结果不确定交顾问用既有内容编辑/assist 处理。
- 写回前复核计划、顾问分配与当前账号权限、资料/关键词、任务和稿件版本；生成成功仅保存 `drafting`，不内审、不准确版本确认、不发布。保留资料引用和真实系统触发来源。
- 服务计划/执行链 GET 增加独立 `trigger_actions`，分别说明内容、网站、监测、报告的手动触发能力、拒绝原因和请求地址；不能从 `update_service_plan` 推导。写端仍独立核验，读取无采集/生成副作用。
- 本机 PATH、服务、进程、常见安装目录、5432/55432端口及测试 DSN 名称未发现可用隔离 PostgreSQL。提供仅允许本机专用测试库的并发领取、周期去重和撤销测试；没有实际运行就明确跳过，不以 SQLite 冒充 PostgreSQL 验收。

实际实现与定向审查：

- `app/seo_content_drafting.py`：以上一次领取、现有assist/额度/operation、恢复取回、材料/权限/版本复核及drafting写入；在`app/seo_content_workflow.py`既有调度接入。配置和允许动作见`app/api/seo.py`，资料不另建表。
- `app/seo_workflow_capabilities.py`与`app/api/seo_service_workflows.py`：四类trigger_actions，读取与写端共用新建阻塞条件；监测额外关键词权限，不从计划编辑能力推导。GET不进行供应商调用。
- UI-09追加缺口：人工登记新增必需source_version/payload_hash、稿件锁和明确428/409；已有complete增加内容锁与edit复核；发布列表逐条complete允许动作/拒绝原因。SEO原分发页保存选择时的版本/hash并防止切换客户后的误反馈，未改SEM前端。
- 旧PATCH发布专项：原后端已拒绝跨状态跳published及受保护稿件page_url编辑，不把可疑路径写成已证实绕过。0105缺version的草稿保存确实可接受，已收紧为428；0104保留旧草稿调用，均不能借PATCH直接发布。当前本地编辑器已按content_id/site加载并携带version、分开正文保存，未重复改造。
- 回归暴露周期抓取同一时钟刻度的竞争：以前只比`last_checked_at > started_at`，同刻人工复检可能被覆盖；改为领取时保存原检查时间、写回比较其是否改变。
- 不把引用格式检查称为事实真伪验收；AI失败/未知不自动重试，真实生成但未采纳不冒称退款。资料/计划/身份变化、取消或人工改稿后不写回。

测试与环境：

- 首轮4文件：111 passed、3 failed；修正配额夹具（既有额度最小为1）、旧能力投影Mock，并修复上述同刻复检竞争后：115 passed。
- 扩展曾出现1项旧测试期待未加锁的调用参数，更新为实际lock=True；另外一次误写不存在的assist测试路径，未运行测试且未记通过。
- 最终15文件定向回归：**482 passed、9 skipped、1 warning**。覆盖自动草稿/四类执行链/确认/人工登记/分发/基础内容编辑/调度/工单权限/页面证据/演示隔离/发布白名单。9跳过=新PostgreSQL并发6例+既有环境3例；warning为既有jieba/pkg_resources。
- 命令：`python -m pytest tests/test_seo_content_drafting.py tests/test_seo_content_workflow.py tests/test_seo_service_workflows.py tests/test_seo_content_confirmations.py tests/test_seo_publication_workbench_contract.py tests/test_seo_distribution.py tests/test_seo_workflow_postgres.py tests/test_seo_foundation.py tests/test_seo_scheduler.py tests/test_seo_cockpit.py tests/test_seo_cockpit_auth.py tests/test_seo_page_capture_api.py tests/test_seo_release_consistency.py tests/test_seo_workbench_publication_page_evidence.py tests/test_seo_demo_runtime.py -q`。
- 前端实际SFC手动登记handler测试 **5/5**：选定版本冻结、更换选择、缺hash/版本与客户切换、409不自动重试、旧范围响应不误反馈；`node --test frontend/scripts/test-seo-manual-publication.mjs`。使用本机已有Vue编译器检查脚本和模板成功；未称完整前端DOM/生产联调通过。
- PostgreSQL运行包和精确环境要求见接口文档；已核查PATH/服务/常见目录/监听端口/测试DSN，没有可用隔离库。没有安装全局服务，没有连接生产数据库；库地址防护的4项测试已实际运行。
- 提交前逐文件自查范围为本批16个改动文件及直接调用链；12个Python文件语法解析、Vue脚本/模板编译、`git diff --check`和SEO源文件白名单全部通过。重点核对锁内版本条件、撤权/取消后的写回、跨租户过滤、默认关闭和读取无供应商副作用；未称独立审查人批准或生产验收。

本批仅本地代码、测试和提交；准确SHA见Git日志。未推送、PR、合并、部署、执行0105或其他迁移、真实AI调用、真实采集/发布。仍待工作台挂载新触发/AI配置/人工登记字段、隔离PostgreSQL并发验收、完整渲染环境与真实账号试点；PDF自动推送及站外通知缺口保持不变。

## SEO-11：DeepSeek 显式路由与目标交付完成

关联 SEO-A02、A04、A05、A07。本批只处理指定的供应商选择和两个任务完成条件，没有扩大为全仓审计。

实现与审查：

- 自动草稿服务计划新增 `content_ai_provider=deepseek` 与 `content_ai_model=deepseek-chat/deepseek-reasoner`，顾问显式选择并冻结到领取/操作摘要。首次生成和一次纠正均显式传入官方DeepSeek地址/key/模型，不再继承DashScope优先路由；只配DashScope、缺DeepSeek或地址无效时转人工，失败不回退其他供应商。
- 复用原assist/配额/operation，成功保存请求模型和供应商响应的真实model（缺失为null）。缓存结果缺少对应供应商证据或模型明显不符不写稿、不盲目重试。原公共assist请求摘要、默认路由和响应格式保持兼容；共享 `app/ai/deepseek.py` 只增加可选响应元数据出口，未改全局模型或供应商默认值。
- 确认并以三个失败测试复现原问题：其他文章归档、七日窗口移出导致目标发布无法done；其他页面变差导致目标已修复无法done。两个任务完成条件现按目标/版本/时间的真实交付证据判断，站点总量留在 `effect_context`，持平或下降不阻挡。
- `page_remediation` 增加同租户/站点/URL最新快照、HTTP2xx、无问题与真实完成run佐证，不能拿人工状态或过滤失败后的旧成功快照完成。同一刻度必须有冻结旧快照ID与更新ID证明先后，旧任务没有ID则要求严格晚于创建。内容仍要求准确版本确认、选定发布记录和发布后自动页面证据；失败/手工capture/错范围/过期确认不能完成。
- 新对象指标仅写入完成证据；`/metrics/snapshot`、trend_7d、共享任务字段和原站点指标口径不改。历史已完成证据不回填，未完成任务按新证据规则接续；前端不得假设completion_evidence.metric_key固定等于baseline.metric_key。无需新增表或迁移，内容链仍需0105。

验证：

- 修复前三个业务复现测试实际为 **3 failed**；修复后首轮 **125 passed、3 skipped**，扩展十文件 **367 passed、9 skipped**。
- 新HTTP层使用 `httpx.MockTransport`，实际执行客户端路由代码但不联网；覆盖DeepSeek优先、纠正请求、失败无回退且退款、缺配置、异常地址、响应模型不符/缺失、原公共assist兼容、恢复旧缓存与模型修改显式授权。
- 最终18文件定向回归 **507 passed、24 skipped、1 warning**。24跳过为工作流PostgreSQL6例、既有工单环境3例、追加的AI operation PostgreSQL15例；不能记为通过。warning为既有jieba/pkg_resources。运行命令：`python -m pytest tests/test_seo_draft_provider.py tests/test_seo_delivery_completion.py tests/test_seo_content_drafting.py tests/test_seo_content_workflow.py tests/test_seo_service_workflows.py tests/test_seo_content_confirmations.py tests/test_seo_publication_workbench_contract.py tests/test_seo_distribution.py tests/test_seo_workflow_postgres.py tests/test_seo_foundation.py tests/test_seo_scheduler.py tests/test_seo_cockpit.py tests/test_seo_cockpit_auth.py tests/test_seo_page_capture_api.py tests/test_seo_release_consistency.py tests/test_seo_workbench_publication_page_evidence.py tests/test_seo_demo_runtime.py tests/test_seo_ai_operations.py -q`。
- 15个改动文件的源文件白名单检查、13个Python文件AST解析与 `git diff --check` 通过。自查限当前差异和直接调用流程，无独立审核人批准或生产验收结论。本批未改前端，不重复累计SEO-10前端测试。
- 测试解释器：`D:/SNIPERS国内版/ai_sni/.venv/Scripts/python.exe`；导入桩：`$env:TEMP/seo-test-pydeps`，设置为PYTHONPATH。桩仅用于缺少Pillow/python-docx/openpyxl时的导入，不代表真实渲染测试。普通隔离回归使用假数据库/供应商配置；真实key未读取、供应商未实际调用。
- 收尾时总控告知已准备本机PG16.15隔离测试库并接手工作流6项和地址防护4项。为固定验收代码，本窗口不再并发编辑测试/执行链，不读取其凭据、不重复执行PG测试；其实际结果后续单独记录，不能把本轮skip改写成pass。

本批仅本地提交 `67975f32`；未推送、PR、部署、迁移、真实采集或发布。工作台需识别新供应商字段和目标证据结构；工作流隔离PG结果已在下方补录，真实数据试点、完整渲染环境及站外通知/自动PDF推送仍待后续验收或实施。

## SEO-11 后续：总控隔离 PostgreSQL 验收已通过

2026-10-07，总控固定 `67975f32bb1175ba21c9f7dabd6b619b24306860` 亲自执行 `tests/test_seo_workflow_postgres.py`，实际 **10 passed、0 failed、0 skipped、1条既有warning**，耗时9.19秒。开发窗口已核对验收记录及脱敏JSON，没有重复执行或读取凭据。以上各批历史skip数字保留，不回写为pass、不重复累加四个已运行的连接防护用例。

- PostgreSQL 16.15，本机专用空测试库、普通测试角色，实际asyncpg/SQLAlchemy；运行前后代码和测试文件哈希稳定、工作区干净。
- 六个真实数据库场景：同UUID并发幂等、不同UUID活动链冲突、周期游标去重、等待请求后的顾问撤权、多个AI工作者单次领取/额度、并发改稿后人工登记拒绝旧版本。另四项验证非本机/错误库/错误驱动/连接附加参数被拒绝。
- 前后测试schema与用户表均为空，清理符合基线；无生产连接、真实客户数据、供应商调用、抓取或发布。
- 测试建最小模型表并省略外键，因此本次通过**不等于完整0105迁移、全部约束/外键、压力测试、真实供应商或线上端到端验收**。原回归中其他3项工单环境用例和15项AI operation数据库用例未被本次覆盖，仍待验证。导入桩不代表图片/Word渲染验收。
- 证据文件：`D:/SNIPERS国内版/梳理-2026-10/项目筹备-20261007/SEO_POSTGRES_ACCEPTANCE.md` 与同目录 `SEO_POSTGRES_ACCEPTANCE_RESULT.json`；JSON记录exit_code=0、code_stable=true、cleanup_matches_baseline=true及完整脱敏pytest输出。

本次仅更新文档并本地提交；执行链/测试文件保持已验SHA内容不变。后续仅在相关代码变化或有新问题时重跑这轮，不再将这六个场景列为“等待隔离PG”。

## SEO-12 预检：完整迁移不能限定到新建 schema，执行暂未开始

2026-10-07，收到推进本地完整0104→0105迁移及真实API联调准备的安排；写入边界为指定本机测试库、本轮自建schema，遇历史迁移不能schema隔离时先报告原因和最小方案。

实际只读检查：使用项目Python的 `alembic.script.ScriptDirectory.from_config(Config('alembic.ini'))` 和 `walk_revisions(base='base', head='0105_seo_content_confirmations')` 读取真实迁移图，未加载env.py、未连接数据库。唯一head为0105，唯一base为0001_initial，可达122个revision（含6个合并节点）；0105父节点为0104，0094→0095_adopt_geo_ticket→0096_sem_tasks→0097_demo_tenant_bindings→0098_demo_binding_no_truncate→0099→0100→0101→0102→0103→0104连续可达。初始临时AST遍历不支持合并/带类型revision声明，改用上述Alembic实际图读取成功；没有据此误报历史迁移缺失。

已确认的执行阻碍（静态源代码证据，不是声称已执行数据库失败）：

- `migrations/versions/20260909_0095_adopt_geo_ticket.py`：第21行固定_SCHEMA=public，第51/74/97/116行catalog过滤public，第169行锁 `public.geo_action_tickets`，随后对public表增加列。此前0046创建的表若只落新schema，0095仍会找public而拒绝；search_path不能重定向显式限定名。
- `migrations/versions/20260909_0097_demo_tenant_bindings.py`：第71–73/100–101行外键明确指向public.tenants/users，第85/110行在public建表，第113行起函数和触发器均固定public。
- `migrations/versions/20260909_0098_demo_binding_no_truncate.py`：第15–16行触发器及函数目标固定public。SQLAlchemy schema_translate_map也不能改写这些原生SQL/catalog字符串；仅增加连接search_path不足以形成隔离。
- `app/seo_main.py`：第70/76/82/120/141行及demo/GEO结构检查固定public。即使绕过历史迁移拼出自建schema，真实健康检查也不会认定该schema已就绪，不能替换健康检查后称真实后端通过。
- 0095、0097、0098的downgrade明确拒绝执行。因此清理不能计划成直接downgrade base；应依据运行前后的对象清单仅清除本轮新增对象，并保护schema本身和原有对象。

最小建议：由总控确认把本轮隔离边界改为**既有专用空测试库中的public**（仍严格校验127.0.0.1:55432、指定库和普通测试身份）。不改历史迁移、健康检查或权限逻辑，不新增高权、不DROP DATABASE。执行前只读核对public的CREATE权限和完整对象清单；发现既有用户对象或所需权限不足立即退出。确认边界后，原样Alembic升0104、插入合成基线、记录数据/对象指纹，再原样升0105并验证表、外键、唯一/检查约束和旧数据保持。成功后按已记录清单清理本轮新建表/序列/函数等，不用无范围CASCADE，不删除public schema。不批准public边界时，替代方案是环境负责人另备可使用public的独立临时库；不能在当前授权下偷偷扩大写入范围。

后端接入状态：**尚未启动，无可交付地址、身份文件或已创建的tenant/site**。迁移隔离问题解决并验证通过后再准备仅loopback服务，启动前验证调度关闭、真实key为空和外部网络动作受隔离适配阻断；复用真实登录/租户/RBAC依赖，使用合成客户和顾问，凭据仅存受限本地文件。数据库写入、服务启动/停止和清理由SEO窗口独占负责，前端待接入信息后只通过API操作。报告时段和种子以创建时的合成数据清单为准，未创建前不发虚构ID或宣称联调就绪。

本次没有读取凭据、连接测试库、执行迁移、创建数据库对象或启动进程；数据库前后对象未重新查询，不能引用前一轮空库结果冒充本轮实测。本次仅文档记录和本地提交，不推送、合并或部署。保留SEO-11十项PG并发验收结论，但不能代替本轮完整迁移验证。

### SEO-12 后续实连预检：public 范围已批准，普通账号缺权限

总控随后明确授权仅在用户提供的空 `127.0.0.1:55432/seo_workflow_test` 库使用public原样运行历史迁移，允许保留合成联调数据直到联调结束；不改角色/库权限、不调用其他库、高权或生产。

本窗口已读取指定受限配置到进程内并用asyncpg只读实连，未打印或复制凭据。2026-10-07实际结果：

| 前置检查 | 实际结果 |
| --- | --- |
| 主机/端口/库 | 127.0.0.1/32、55432、seo_workflow_test，全部匹配 |
| 当前身份/版本 | seo_workflow_tester，PostgreSQL 16.15 |
| 角色权限 | rolsuper=false、rolcreatedb=false、rolcreaterole=false |
| 用户关系对象/版本表 | 空；无表、视图、序列、索引或alembic_version |
| 用户函数 | 空 |
| 非系统schema | 仅public，属主pg_database_owner；数据库属主postgres |
| 专用库CREATE | true（可创建新schema，解释此前隔离并发测试为何能通过） |
| public USAGE / CREATE | **false / false**（无法在public运行历史迁移） |

首次带断言的前置检查在public CREATE处退出，未执行迁移；随后只读细化权限定位发现USAGE也缺失。当前阻碍已不是范围授权，而是这两项schema权限。没有尝试GRANT、修改schema/数据库属主、角色提权、create_all、stamp或任何DDL。因为未发生写入，没有新增对象需要清理，后端仍未启动。

环境负责人最小修复方案：仅连接上述本机专用测试库，以现有有权身份给测试角色 `GRANT USAGE, CREATE ON SCHEMA public TO seo_workflow_tester;`，不要授予SUPER/CREATEDB/CREATEROLE或其他库权限。此SQL仅为准确缺项说明，**本窗口未执行**。授权完成后仍须重做目标/空库/权限前置核验，再运行真实0104基线及0105升级；迁移通过前无API地址或合成身份可交付。无需重复授权业务范围，不将权限不足转成重新向用户请求整个任务许可。

再次复核（收到“授权生效”通知后）：使用新连接确认目标仍为127.0.0.1:55432/seo_workflow_test，session_user/current_user均为seo_workflow_tester；public USAGE/CREATE仍为false/false，用户对象及函数仍为空。进一步直接读pg_namespace得到 `nspacl={pg_database_owner=UC/pg_database_owner}`，尚无测试账号授权项。首次复核查询因把CREATE当未引用别名产生只读语法错误，修正别名后才取得上述结果；没有将语法错误误报为权限失败。这表示当前指定目标连接仍未观察到授权，需要环境负责人核对授权目标实例/库及事务是否提交；未断言其他数据库发生了什么，未越界尝试其他库。仍未执行DDL、迁移或启动后端，不能按口头通知跳过实际权限门禁。

## SEO-12 完成：真实迁移与本机 API 已就绪

上述权限历史已解决：用户再次明确授权到目标库后，本窗口新连接核对USAGE/CREATE=true、普通角色、空对象基线，才实际执行DDL。完整操作、接入范围、凭据路径与清理步骤见 `docs/SEO_LOCAL_ACCEPTANCE.md`；未读取生产环境或改角色权限。

- 新增 `scripts/seo_local_acceptance.py`：显式单库目标、真实Alembic迁移、合成种子、旧表指纹、约束探针、只监听loopback的真实FastAPI、只供SEO操作者使用的撤权/恢复CLI、受限前端配置导出和RESTRICT清理计划。没有create_all/stamp、数据库删除或自动清库。
- 原样执行122个revision构成的历史图至0104，再升0105。首次验证脚本因catalog内部char由asyncpg返回bytes而误报外键缺失，未计通过；已改SQL显式::text并禁止空基线。核对两张新表无数据后，实际downgrade到0104，记录102张已有表的行数/SHA256，再upgrade0105验证保留性，全部一致。
- 两张新表8条FK的真实目标与删除动作、CHECK/UNIQUE及10项事务写入探针通过；探针rollback后留一个真实顾问assignment供联调。保留105张表（含版本表）、97条序列、375个索引、2个函数，全部public/测试账号所有；原plpgsql扩展未动。
- 本机 `http://127.0.0.1:8031` 已实际启动，健康200/schema=ok/0105。四种合成身份真实登录通过；客户/顾问的站点、计划、状态、任务、内容读取200；跨客户403、未登录401、客户/未分配顾问改计划403；AI/抓取/发布写入403、API Key403、非本机Host400。没有替换鉴权依赖或固定超管。
- `scripts/seo_local_auth.py` 仅用于本地宿主，补齐旧SEO分支缺少的共享会话只读catalog；真正JWT、User/Role、TenantModule和现有module_scope决定结果。已实测客户/顾问/外客户的modules与按模块筛选tenants均200且范围隔离。生产共享认证网关部署不在本次结论内。
- 主合成tenant/site=1/1，外客户2/2；草稿1、ready稿2、撤权专用ready稿3、task1、keyword1、fact1、page1。第二稿由真正计划run→PATCH→提交审核→审核→advance建立，第三稿由本地种子建立后经真实审核API到ready。客户仅view权限，确认入口可用、编辑/代确认不可用；顾问assignment仍active，撤权留到UI同步点。
- 所有真实key为空，关闭调度、抓取和页面capture；运行进程仅允许向指定PG建立连接，禁止外部DNS/子进程。人工发布仅登记合成事实；没有生成自动页面证据、没有完成SEO交付效果、没有真实流量或冻结月报种子。网页适配/报告完整浏览器矩阵仍明确未验。
- 真实Pillow12.3.0/python-docx1.2.0/openpyxl3.1.5及依赖仅安装到TEMP隔离目录，运行后端未使用导入桩；未把依赖安装等同于完整渲染验收。
- 新运行包测试先20通过，增加本地catalog权限/过期模块后最终 **23 passed**。Python编译/AST、git diff --check及SEO范围白名单通过。真实数据库和HTTP检查另列，不与单元测试混算；不重复此前10项PG并发或总控40项前端检查。

后端和专用库由SEO窗口持有生命周期，保留供UI-12真实浏览器接续；不提前撤权、清理或让前端直写数据库。身份文件和导出的TEMP配置均受Windows ACL限制，密码/JWT/数据库凭据不进聊天或Git。当前批次仅本地提交，不推送、合并、部署或生产迁移；总控单独提交的前端依赖修复399afdff不属于本批改动。


## UI15 SEO人工消息：本机实现与真实联调（2026-10-08）

功能提交 `9f3037812d1efbe951c1b8056f0adc1346f64805`：tenant/site/content严格定位的客户—活动分配顾问文本会话，GET不建会话/不推进已读，UUID幂等发送、游标历史分页、服务端身份和UTC时间、显式个人单调已读。消息独立于审核/客户确认/发布/工单；顾问撤权或降级view不能退化为客户绕过门禁。participant是游标与发送参与记录，不是静态ACL。

本机按真实Alembic执行0105→0106，104张原表指纹保持；新三表仅本机测试库，未连生产。健康支持0105/0106及必要消息结构，旧确认和工单门禁继续可用；未知/多revision拒绝。生产顺序及三模块已知源码评估见`SEO_LOCAL_ACCEPTANCE.md`，仍要求先单独批准兼容代码部署、再单独批准数据库迁移；旧0105-only SEO包不可作为0106数据库的无条件回滚包。

后端定向回归276通过/8历史环境用例跳过；本轮真实PG并发、权限、撤权、游标、结构和只追加测试均执行。后续把新消息、确认和本机runner测试加入CI入口，门禁相关78项通过（包含前述用例，不与276累加）。本机操作工具对异常只输出脱敏摘要；未启动CI远程运行。

真实HTTP和浏览器测试使用新增合成稿64（tenant/site=1/1），25条合成历史+3条浏览器消息，共28条，同键重放未增加记录；客户read_cursor28、顾问0。撤权/恢复握手已执行并恢复active，稿件仍drafting/v1，无审核时间/发布时间。102张原业务表（原稿件排除新增64逐行比对）指纹未变；仅登录时间、测试顾问分配更新时间是预期元数据变化。脱敏对账见 `C:/Users/Administrator/.secrets/seo12-local/ui15-database-reconciliation.json`。

前端原始真实写测试报告 `C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui15-real-TWZN7H/report.json` 绑定frontend9971b3e60383a87118bd10d02bce67a7cb132d3f/backend9f303781：互发、持久化、同键恢复、显式已读、分页、390布局、跨范围和撤权恢复业务断言完成，但总结果failed，因为脚本把浏览器内置data图片误判成外部请求。保留该原报告，不能改写为pass。前端正在窄修正判定及刷新后滚动位置，并使用已有消息只读复核；没有重放发送或撤权。

本轮仅本地提交与本机测试，未推送、合并、部署或生产迁移；8031隔离后端继续运行9f303781，消息、旧UI12/14数据和凭据留在既有受限目录，尚未清理。首次真实平台发布、生产共享登录、SEM/GEO部署版本对账仍不在本次验收范围。


UI15后续收尾：前端完成滚动及请求分类窄修复，最终产品SHA `934a9263af611c86e326083f81d96f694bae7dc8`。只读复核报告 `C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui15-real-JM4q6e/report.json` 已实际读取核对：result=passed、sourceTreeClean=true、backendCommit=9f303781、contentId64、messageWrites=[]；复核历史分页、原消息刷新持久化、390布局和异站范围清理。除两次登录其余GET，未重发消息或重复撤权。写入业务证据仍引用原TWZN7H的7个已完成case和数据库对账，不把该原始failed总结果改成pass；这是分阶段验收，不声称最终前端SHA又重跑了写业务。9f303781之后的本窗口提交仅测试门禁、操作脚本错误脱敏和文档，app/迁移源码无变化，运行后端保持原验收版本。


生产基线更正：此前发布顺序中“数据库仍0105”的假设已删除。用户提供的生产基线为0104，实际revision仍需现场只读核实；0105/0106均未获准生产执行。兼容代码健康检查覆盖0104/0105/0106，未0105时新增客户确认接口拒绝，未0106时消息接口503。若实际0104，独立数据库审批必须覆盖0104→0105→0106完整计划；本次仅改文档，不改代码或执行任何迁移。

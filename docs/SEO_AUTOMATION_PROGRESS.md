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
| SEO-09 | 本批本地提交，见 Git 日志 | 周期诊断整改、排名异常待办、冻结月报与执行链只读投影 |

以上均为本地提交。当前没有推送、PR、合并、部署或生产迁移。SEO-01–07 完成的是基础契约和局部接续，不是完整 A01–A07 自动化。以下状态按实际执行链重新标注；不能用事实汇总或单点接口代替周期任务运行。

当前剩余项：

- SEO-08/09 已实现本地辅助执行链；真实 PostgreSQL 并发、工作台前端挂载、生产资源授权和外部平台验收仍未完成。网站诊断有每轮10页上限，排名异常首期为百度桌面全国最多200词，报告为冻结 HTML，不称全域/全渠道自动化。
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
| SEO-A04 内容制作与稿件确认 | SEO-01/08 | 首条辅助链本地实现 | 选题稿件由计划生成，顾问制作和审核，准确版本确认后继续；不自动调用付费 AI |
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

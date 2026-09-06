# GEO Brief、跨语言证据与只读接口实施记录

2026-09-06，分支 codex/production-geo。工作基准 d100907；当前仅本地修改，未提交、推送或部署。未调用真实采集/生成，未修改生产配置或数据库，未改写历史文章。对照原型 20260906-45；不修改驾驶舱原型所在工作区。

## 已实现

1. **Brief 与正文分离**：删除生成器向 disclaimer 追加 Brief/策略的代码。Brief 仍作为模型的内部创作要求，并保存在 generation_meta，不能当作事实证据。补充同名主体不可混用的生成指令。没有批量清理历史稿；这不是全文事实准确性的保证。
2. **版本展示**：编辑器流程与版本栏展示真实 version_no、article_id、来源及手动保存的 from_version；取消写死“生成母稿 V1”。AI 生成、规则草稿、手动保存和导入分别标注，历史缺来源显示未知。
3. **跨语言证据**：逐句证据新增 review_reason、evidence_candidates，原文保留否定/条件/型号/数值；中文与拉丁文字语言差异仅提供待核验候选，不构成翻译支持证明。补充常见英文适用性/效果断言及删否定的负例检查。生成错误、正文检查及编辑器说明区可显示跨语言待核验；仍使用现有客户审核，没有增加第二道审核。
4. **工作台接口**：新增下面 9 个 GET，以及 frontend/src/api/geoReadModel.js 的调用适配。未将驾驶舱界面切换到真实采集模式。

统一前缀 `/api/v1/geo/integration/read`：

|路径|内容|
|---|---|
|`/answers`|回答分页、明确时区、历史提问/模型、来源与正式准入解释|
|`/answers/{snapshot_id}`|同口径回答详情及完整原文|
|`/period-context`|完整周、前周、覆盖门槛与比较条件；不给第二套指标数字|
|`/capabilities`|已有配置及缺项，不初始化、不试连|
|`/content-tasks/{content_task_id}`|保存版本与真实来源、渠道稿、发布记录和指标任务关系|
|`/patrol-runs`、`/patrol-runs/{patrol_run_id}`|已有巡检及逐单元结果/失败分类|
|`/async-jobs`、`/async-jobs/{async_job_id}`|已有异步任务、进度及已验证归属的母稿产物|

全部校验 tenant_id，使用独立 autoflush=False session，并在读取前设置事务级 REPEATABLE READ、READ ONLY。不调用旧查询中的 ensure/reconcile，也不取得执行锁。stale 仅是耗时超限提示，保留 stored_status，不冒充已失败。

正式指标仍由 `/integration/metrics/snapshot` 和 `/integration/metrics/dictionary` 返回。共享五字段和 trend_7d 格式未变；将原来源/巡检校验提取为共用原因函数，避免展示和正式统计使用不同准入规则。单条不合格、窗口外、整周不足分别表达；模拟、人工、未知来源不进入正式指标。

## 契约实施细节

- 回答 cursor 签名绑定租户、筛选、已解析 week_end、limit、最大 ID 和排序位置。回答按时间/ID 倒序，同时间稳定翻页；游标不能跨客户或筛选复用。未知时间数量单独返回。
- 巡检/异步列表使用 limit（默认20、最大50）及 next_before_id 分页；不是回答 cursor。省略 before_id 从最新开始。
- `/capabilities` 的 configured_mode 只是配置推断；monitoring_stance=simulation 不因存在平台 Key 而宣称真实；real_only 缺 Key 显示 unavailable。最终 effective_mode=null，mode_basis=execution_request_required，connection_verified=false。实际请求的策略、prefer_real 和可用运行能力会影响结果，执行前不能承诺实际来源。
- 任意模型别名不等于不可变修订号，model_revision 保持 null。无历史元数据不回填当前配置。
- 异步/巡检错误使用脱敏分类，避免第三方返回体泄露凭证；未知错误不透传原始 request_meta。母稿生成只返回已成功且归属核实的 article_version 引用，失败不把旧稿当新产物。
- 内容查询为已保存对象视图，不触发评分或刷新证据缓存；跨语言最新结果需走既有检查/生成流程才能保存到原任务。当前没有改写历史缓存或自动核实翻译。
- 新模块提供接口及前端调用适配；驾驶舱最终页面接线、真实供应商调用和生产上线不在本轮执行范围。

## 本地验收

- 新增测试覆盖 Brief 不进入正文、版本来源、双向跨语言待核验、英文否定不可删除、模拟/人工/篡改/跨租户证据、整周不足与行资格分离、窗口外/缺模型、游标篡改/租户绑定、时区校验、只读事务启动、空配置不初始化及超时查询不回写。
- 后端：**927 passed，17 skipped**。命令为 `python -m pytest tests -q --ignore=tests/test_analysis_reports.py --ignore=tests/test_keyword_refresh.py --ignore=tests/test_seo_foundation.py`，使用本地测试占位配置。上述三个测试文件在全仓收集时依赖 Linux fcntl，Windows 环境无法导入，未修改 SEM/SEO/调度器规避。
- 前端：`node --test tests/*.test.mjs`，**143 passed**。
- 前端：`npm run build` 通过；依赖包注解和大体积 chunk 提示仍存在。
- diff 空白检查通过。没有修改 migrations、SEM 或 SEO 业务文件。

测试边界：纯查询事务的声明和业务查询路径已经离线测试，**真实 PostgreSQL 下的事务只读强制、SQL执行/查询性能与生产路由联调仍待对应环境验收**。17 项跳过不算通过。H1 真实出稿复验仍待新版本上线后执行，历史 V1/V2 保留对照；本轮自动测试不代替 H1，也不证明发布后的可见度改善。

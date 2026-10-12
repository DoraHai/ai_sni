# 2026-10-11 本地验收证据

本目录保存独立测试导出的证据，使用合成业务对象和隔离 PostgreSQL，不包含生产客户资料、JWT、口令或供应商认证头。顾问工作台产物对应的最终提交由清洁构建的 `release-manifest.json` 记录。

本目录的JSON/XML与评分输入目录均用局部Git属性保留原始字节，避免跨平台换行转换后误认原SHA256。证据元数据整理时不改变原HTTP导出；原导出hash仍可直接核对。

| 单元 | 首轮冻结提交 | 证据范围 |
| --- | --- | --- |
| SEO | `1525fa4cd97480b19726bbb83d3eca533d0d50bd` | 真实 JWT / PostgreSQL 的普通 HTTP 样例、9 类 health 响应、10 个守卫样本和10 份历史模型响应回放 |
| GEO | `bc13259e20478ff78595df6068c8c00c04bd8561` | 独立真实登录链 3 项、旧 geo_ci 读取 11 项；普通 HTTP 样例使用合成 AuthContext，与真实登录证据分开 |
| 超管 | `88a591101b28827468a188135f0e48c120965d03` | 冻结前端严格解析器核验两模块各9类实际 health 响应 |

`geo-automation-v2-real-auth-evidence-*` 明确记录 `/auth/login → JWT → DB User/Role → scoped auth → GEO 路由`，仅覆盖数据库 session 到隔离 schema，没有覆盖鉴权依赖。`geo-legacy-pg-evidence-*` 记录临时测试数据库、角色和精确 HBA 条目已清理。

`linux-automation-validation-*` 是临时 QEMU/Alpine 内核实测，35项通过、0跳过，保留 XML 和源码 hash。GEO 调度源码来自 `0501b9f1` 的仅源码归档；调度源与四个测试文件在当前 GEO 候选中没有变化，发布预检仍逐项比较。补充进程测试另对当前工作台文件检查。来宾依赖不等同生产固定版本，隔离回调也不验证线上消费者或服务管理器。

`automation-*-qualification-guards-*` 是合成输出检查；`automation-*-recorded-replay-result-*` 回放 2026-10-10 的真实供应商历史回答，输入为合成设备业务资料。没有新增模型调用，没有可供宣称合格的真实客户业务评分。报告的85分是待审阅门槛；`score=null` 为未评分。

HTTP 快照数有重复，不与独立测试数相加。health 中未知状态保留 null；当前进程观察不代表全部 worker 健康。所有证据都不授予生产发布、DDL 或审批权限。

使用 [发布与回退清单](../../automation-release-runbook-20261011.md) 中的只读预检命令，可将 `--seo-http`、`--geo-http`、`--linux` 改为本目录保存的对应文件。最终本地提交与构建 manifest 一致后，预检才可通过；生产门槛仍单独列出。

## 顾问与客户交付补测

用户恢复测试后，前端修复错误任务回包，SEO/GEO 修复复检等待期间撤权后的结果采用，GEO 同时修复站内接口权限映射。新的证据按提交号保留，不覆盖首轮文件。

| 单元 | 本轮功能提交 | 当前验证 |
| --- | --- | --- |
| 组合工作台 | `5968825710aec8081007eb5e90127a1831bf6ee3` | 站内及交付 48 项通过（含 4 项真实 Edge 场景），契约 147 项通过；前端报告明确测试时修改中构建与功能文件 hash。修复前顾问 38 项作为基线单列 |
| SEO | `75dfa5e9fc75af51a27f4bc221ba3008ca7f1724` | 348 项通过、0 跳过；XML、真实登录闭环样例与去敏元数据单列 |
| GEO | `bf6483d337398ba35aa2841b27545c06fb0cb896` | 站内组 148 项通过、0 跳过；真实登录/JWT/数据库闭环元数据与 XML 单列；项目自动化 JWT 3 项、HTTP/health 导出 1 项通过 |

`advisor-delivery-browser-evidence-*` 与 `advisor-delivery-contracts-*.tap` 保存前端测试结果。浏览器中只有合成客户与拦截 HTTP；后端集成测试没有经过浏览器。两类证据可以联合核对分工与状态，不能宣称完成了同一浏览器连真实数据库和真实供应商的端到端测试。

最新冻结样例为 `seo-automation-v2-http-samples-75dfa5e9-20261011.json` 和 `geo-automation-v2-http-sample-496b97fe-20261011.json`；只读预检应使用这两份对应当前模块提交的文件。SEO 107、GEO 12 个普通响应快照和各 9 类 health 解析全部通过，快照存在重复，不与测试数量相加。GEO 普通导出仍标明合成 AuthContext，其真实登录证据使用 `geo-onsite-real-auth-*`。

GEO 最终冻结提交为 `496b97fe2127dd725c43697e965bfc53e2acf003`：其后两次提交仅修改导出测试，应用源码与功能提交 `bf6483d3` 一致。导出元数据缺失曾被严格校验拒绝，现通过真实测试前后 HEAD、源文件 hash 与 clean 位绑定；显式 `GEO_AUTOMATION_FREEZE=1` 强制清洁导出，普通开发测试保留真实 clean 位而不因此失败。最终只重跑导出节点 1 项通过；148 项功能回归仍对应 `bf6483d3`，不宣称在新 HEAD 整组重跑。原功能元数据的旧普通样例 SHA 为历史记录，普通响应以最新冻结文件为准。

各组测试有重叠，不汇总为一个独立测试总数。本轮没有新模型付费调用、真实官网写入、生产变更、SEM 接管、发布分发或负责人交接；业务质量评分与现场试运行继续按原验收门槛执行。最终组合工作台提交和构建以清洁 `release-manifest.json` 及只读发布预检记录为准。

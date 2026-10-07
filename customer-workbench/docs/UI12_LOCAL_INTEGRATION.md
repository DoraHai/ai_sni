# UI-12 本机真实联调准备

状态：接线与用例准备，尚未进行真实API/PG联调。数据库由SEO窗口独占准备；总控明确授权后才运行真实登录与业务写入。所有产物限本机，推送、PR更新、合并与发布由总控安排。

总控后续明确：历史迁移链写死public，已授权SEO在专用空库 `seo_workflow_test` 的 `public` 执行实际迁移；因此隔离边界可以是该独占测试数据库，不要求随机schema。UI仍等待地址/身份与运行放行，不自行迁移或写表；清理由SEO负责。

## 本机宿主与登录边界

`scripts/local-backend-host.mjs` 使用临时自签证书，仅监听127.0.0.1。只接受显式127.0.0.1或::1后端origin；不读生产环境文件、不连接数据库、不注入身份、不返回合成业务接口结果。`/api/v1/auth/*`、`/api/v1/seo/*` 原样转发方法/正文/鉴权及服务端状态，保留报告ETag和字节；不跟随重定向、不重试写入。日志只含method/path/status，不含密码、令牌或响应正文。

工作台从既有四文件构建读取，启动时核对产物和canonical会话源码哈希。`/login` 是明确标识的本机测试宿主页：真实POST auth/login → 原 `session.setAuth(token,user,false)` → 真实GET auth/tenants → 原 `session.setTenants` → 同源返回工作台。构建入口自行从原sessionStorage读取登录结果，继续真实me/modules/tenants/sites预检。没有手填token、测试身份注入全局变量、或第二套令牌存储。

**覆盖原session bootstrap与登录跳转；不等同于原LoginView.vue整页/验证码/登录站发布验收。** 没有修改原frontend、鉴权源码或生产构建的HTTPS要求。测试登录脚本仅在本机宿主内存构建，未加入生产app.js。证书只在TEMP短暂保存，不安装系统信任；自动浏览器仅放行该临时证书的SPKI，关闭宿主时移除其证书文件。

接线自测 `npm run test:ui12-host` 使用独立传输探针：上游故意返回409与503，只核对TLS代理、哈希、同源边界、真实浏览器的原会话bootstrap。它不是FastAPI、没有PG、不能报告为真实业务联调成功。

2026-10-07实际准备验证：该探针最终2/2通过，脚本语法检查与Git空白检查通过。首次浏览器断言错等内部错误码，修正为已有503提示；其后外网检查把Edge密码框自带data图标误记为外网，收窄为HTTP(S)网络请求后通过。没有改业务代码或放宽生产门禁，也未运行真实预检脚本。按总控要求不重复已通过的传输探针。

## 等待SEO/总控提供

- loopback后端地址、Git SHA、专用schema名称、迁移0104→0105结果与运行责任。
- 合成tenant/site及活动顾问分配、顾问/客户账号密码的TEMP配置文件；不用生产账号或API Key代替角色。
- 明确启用的外部AI/网页适配及控制方法：固定响应、失败/结果未知、网页证据生成；外部平台发布不执行，以测试事实模拟人工登记。
- 可重置的草稿/关键词/事实资料、网站页面、上月报告种子、旧证据/缺字段用例。
- 总控通知允许本UI进入实际API写入；SEO仍负责schema创建、种子、迁移与清理。

配置文件仅放TEMP，键为 `environment_kind: "isolated-local-pg"`、`backend_origin`、`backend_commit`、`database`、`schema`、`tenant_id`、`site_id`、`advisor/customer: {username,password}`、`external_adapters`。`database/schema` 是总控/SEO交接的环境标识，预检脚本不直连DB验证或更改它；允许 `seo_workflow_test/public`。不要提交配置或在报告打印凭据。

授权后设置 `UI12_CONFIG_FILE` 为配置文件绝对路径、`UI12_REAL_API_AUTHORIZED=true`，执行 `npm run test:ui12-preflight`。它实际登录两种身份并在浏览器读取首页、计划、进度、数据，不发业务写入；登录本身会更新后端登录记录，亦须等授权。报告输出TEMP，明确标为预检，不能作为下面完整场景的通过报告。失败不重试登录/写入，先核对路径、HTTP状态及脱敏字段差异。

手动宿主使用 `UI12_BACKEND_ORIGIN`、可选 `UI12_PORT` 后执行 `npm run preview:backend`。自动浏览器使用启动返回的SPKI；不全局关闭TLS验证，不将上游地址设为生产。

## 完整场景与证据矩阵（待后端就绪执行）

| 阶段 | 合成角色和浏览器动作 | 必须核对的真实API/PG证据 | 外部适配边界 |
| --- | --- | --- | --- |
| 登录/范围 | 顾问、客户分别从未登录入口跳转并登录；刷新、错误站点、会话失效 | auth/login、me/modules/tenants；workbench/sites；服务端实际权限与归属，跨范围被拒 | 无模拟身份响应；原登录UI整页单列未验 |
| 计划 | 客户只读，顾问修改方向、选题、备注；读取事实和关键词；明确开启AI；按revision保存 | service-plan GET/PUT；facts与keywords同站点；模型与授权人由服务端返回；旧revision冲突后重读 | AI配置可用不等于已调用 |
| 新任务 | 顾问明确触发content，记录UUID；进入列表与详情核对ID/request_key | service-plan/run、executions GET，任务真实落PG；进入页面仅GET | 后端任务执行须只调用已声明AI适配，不能触达真实供应商 |
| 草稿与内审 | 从任务打开稿件；修改正文保存；提交审核；复核退回再修改，重新提交并通过 | content-assets精确读取/PATCH、submit-review/review；版本递增、原字段保留、审核门禁 | 若使用AI草稿，报告注明其生成文本来自固定测试响应；数据库持久化与状态机真实 |
| 客户确认 | 客户核对准确版本确认；另用退回/改稿场景验证旧确认失效后重新确认 | delivery、confirmations；actor_mode=customer_direct、版本/hash、后端确认记录 | 不把客户确认当发布 |
| 顾问代确认 | 独立内容任务或经合法退回再审核的版本，由顾问明确代确认 | actor_mode=advisor_proxy、活动assignment、真实actor；客户不能代确认 | 不能通过替换前端角色伪造顾问 |
| 人工登记 | 顾问按已显示准确版本登记合成公开链接与时间；已有记录只有逐条complete允许才回填 | publications/manual或/{id}/complete；版本/hash、published_at、页面核验queued与最终证据分开 | 这是假定测试发布事实的人工登记；不宣称真实平台发布/人工访问已验 |
| 页面证据/任务完成 | 等SEO测试网页适配产出证据，顾问明确接续；读detail与service-status | content-workflows/{id}/advance、真实任务状态、target scope/source_version/publication_id、PG证据ID；effect_context独立且可下降 | 抓取响应模拟，后端校验/状态持久化真实；不宣称公网访问通过 |
| 报告 | 顾问触发report、按服务端资格接续，下载冻结HTML并保存绑定hash说明；客户只读 | service-cycles/run、executions/{id}/report真实字节与ETag/SHA256、explanation角色/hash、完成记录 | 统计来自合成PG数据；不是真实客户月报、PDF发送或客户签收 |
| 失败/兼容 | 旧证据、缺response_model、过期版本/撤权、未知写入结果；显式刷新 | 精确路径/status/脱敏字段；不自动重发，不把缺数据当0或完成 | 网络丢响应可在测试代理显式适配，但须记录哪一步模拟，禁止隐式修改真实业务响应 |

每次完整运行记录前端/后端SHA、迁移/schema、合成角色ID、task/content/version/publication/report hash、实际API路径和状态、外部适配名称/次数。由SEO提供PG落库及后台执行证据；UI不抢占数据库或直接写表。不能覆盖的场景标未执行/阻塞，不用旧内存夹具结果补齐。

## 最短业务浏览器脚本（准备完成，尚未实际运行）

`node scripts/ui12-real-scenarios.mjs workflow` 复用上述配置与授权开关，通过工作台按钮依次完成：顾问轻改/提交/审核→客户准确版本确认→另一篇ready稿件顾问代确认→旧登记表与合法退回/改稿形成真实409冲突并核对无新增发布、无重发→第二篇合成发布事实登记→已知任务列表/详情。客户编辑和代确认按钮同时断言禁用。没有手工注入token、直接SQL、管理写入或伪造API响应。

SEO交付额外配置：`external_operations_disabled: true`；`scenarios: {draft_content_id,proxy_content_id,task_ids,revocation_content_id}`；`publication: {synthetic:true,page_url,platform_name,published_local_time}`。draft稿件须在planned/drafting且绑定关键词，proxy稿件须ready未发布，两个ID不同；已知任务需在首个20条进度列表内。发布时间为北京时间datetime-local字符串。外部网络禁用和适配由SEO实际保障，配置声明不是UI独立验网证明。

撤权由SEO在独占库的管理流程安排，随后执行 `node scripts/ui12-real-scenarios.mjs revoked`，使用同顾问账号及另一个ready未发布稿件，核对真实assignment=false及顾问代确认/编辑/登记按钮禁用，除登录外仅GET。该模式只断言撤权后重进页面，不声称已覆盖撤权瞬间旧按钮提交的竞争；后者等待SEO提供同步方式后补充。

报告只落TEMP，列明方法/路径/HTTP状态、角色actor、版本/hash、发布ID、任务阶段和模拟外部边界；不保存账号密码或登录响应。任何失败立即停止当前链，不自动重放已完成业务操作。预备脚本仅做语法/差异检查，不重复已通过依赖或代理探针。总控已授权在SEO主动交付已核验本机URL、合成身份/对象、禁用外部操作和生命周期清单后开始实际API联调；未完成交付前不运行。

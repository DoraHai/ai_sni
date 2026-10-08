# UI-08 执行链页面交接

2026-10-07。契约来源：SEO工作树本地 `f9a22877c090b9def66f0391e6fe5c6e2d6c5c7b` 的 docs/SEO_AUTOMATION_API.md；窄读 app/api/seo_service_workflows.py、app/seo_service_workflows.py、app/api/seo.py 与任务payload核对。未修改SEO工作树，未调用生产。

## 已挂载页面与准确接口

| 页面/操作 | 契约与行为 |
| --- | --- |
| 进度 | GET /api/v1/seo/workbench/executions，固定tenant/site，page/page_size=20；按服务端total翻页、四类任务分组，显示周期记录/阻塞/下次符合时间，当前页无此类不解释为全量不存在 |
| 执行详情 | GET /workbench/executions/{id}?tenant_id=&site_id=；阶段、状态、计划修订、有效暂停、等待角色、触发者、任务/阶段时间、关注期限、历史截断、页面/关键词依据、完成证据 |
| 内容接续 | POST /workbench/content-workflows/{id}/advance，tenant_id/site_id和可选publication_id；不能把任务advance当发布按钮。准确稿件入口仍走delivery/确认客户端 |
| 网站/监测/报告接续 | POST /workbench/executions/{id}/advance，tenant_id/site_id；失败页面重试附retry_page_id，限服务端retry_page_ids |
| 顾问说明 | 同一advance附explanation（1–4000字）和已读取report_sha256，客户按钮禁用，409要求重新读取，不自动重发 |
| 取消 | DELETE /workbench/executions/{id}?tenant_id=&site_id=；只用server cancel=true，保留任务、报告与外部事实；暂停不妨碍服务器允许的取消 |
| 下载报告 | GET /workbench/executions/{id}/report，读取已存HTML；校验text/html、ETag和实际SHA256后下载本地.html，HTML从不注入工作台DOM。不是PDF、不是发送或签收 |
| 服务周期 | 原service-plan GET/PUT，新增content/website/monitoring/report开关及间隔/页面上限；严格expected_revision和update_service_plan资格，显式保存，核对返回值 |

路径全部由客户端固定构造；不把links当任意URL代理。服务端标准任务payload不带tenant/site，所以读响应同时校验详情链接的准确范围及ID、action_type与允许动作。写后重新GET详情取新资格；SEO-08 advance原始task不含投影资格，不能沿用旧按钮。401/403、范围变更清空；迟到响应丢弃，写结果不明只重读。

## 产品语义

- 进度现在是实际任务页；SEO工作/数据仍是service-status持久化事实准备情况。ready不能推出任务完成，done缺completion_evidence明确显示证据缺失，不编百分比。
- waiting_for和assignee_role是角色，不是个人负责人；assignment是创建时依据，不当当前授权。next_due_at不是保证执行时间；notification_sent未记录时不声称通知。
- 网站只选已登记页面，展示逐页状态、错误、快照/run/整改任务引用；人工修改与真实复检不可省略。监测展示缺报/过期/下降原因、原始观测和恢复目标，保留remaining_issues/resolved_snapshot_ids，不主动发排名请求。
- 月报是上一个已结束北京时间自然月的冻结HTML；缺统计/无截图/不能单篇归因等保留。顾问说明、真实actor/时间和冻结原报告分开，客户不签收报告。
- 周期开关初始默认关闭，页面读取沿用服务器已有值；不会因进入页面自动开周期或POST。保存时内容/网站间隔1–90天、网站每轮1–10页、监测1–30天；监测最多200个active关键词且启用需keyword edit。无该权限时禁用并省略监测变更，不覆盖旧值。
- 关闭周期仅停止新任务，不是取消现有任务；暂停停止新动作，已开始请求仍可保存事实。页面显示内容制作/内审/渠道、网站修改复检、排名新观测、报告说明等人工边界。

## 验证范围

`npm run test:ui08` 先构建，再执行5个契约用例及2个Edge实际DOM用例：四类读取、权限过滤total、精确范围、SEO-08/09不同接续路径、失败单页允许集、暂停取消、报告ETag/字节hash、错误哈希409、未知写不重发、迟到范围变化、默认关闭/显式周期PUT、浏览器HTML下载、客户禁写/顾问说明、分页25项、503/404/资格撤销、390px无横溢出。API仅指向127.0.0.1假会话/内存契约服务。

UI-04/05相关回归：契约28/28、原连接DOM1/1通过。没有重复全仓或独立演示全套；本批未改独立演示业务。页面目检后把逐页/关键词依据提炼为可读字段，完整原始数据保留折叠入口，避免主流程堆JSON。

## 真实端到端仍缺什么

1. 原宿主入口补丁与同源静态发布尚未启用；SEO-08/09本地代码尚不代表目标环境可用。仍需0105、普通实名客户/顾问分配、双view/edit及监测额外keyword权限的真实范围验收。
2. 本轮只以契约夹具验证UI消费，没有在本窗口启动真实后台调度、数据库工作流、AI、排名供应商、网页采集或渠道发布。任务接续是否生成真实快照/报告和满足完成证据，需获准环境联调。
3. 内容制作/轻改/提交审核/渠道选择与人工发布回填、网站实际修改与单页audit、原始页面/排名快照和整改子任务详情尚未挂载；当前显示真实引用和缺项，不伪造可点击证据。
4. 手动新建内容/网站/监测/报告执行链（service-plan/run、service-cycles/run）尚未挂载：当前契约只在任务投影给advance/cancel/retry/explain资格，未给新建动作能力标志。不从计划update资格自行推出trigger资格。周期配置已挂载，明确保存可能授权后续调度，进入页面不会触发。
5. 日期/主题筛选无服务端契约，不做假筛选；真实消息、站外通知、SEM/GEO执行链仍待接入。

代码：js/seo-execution-client.mjs、seo-execution-view.mjs、seo-cycle-config.mjs及connected-workbench实际DOM；host白名单和服务计划客户端同步扩展。仍只本地提交，不推送/合并/部署。

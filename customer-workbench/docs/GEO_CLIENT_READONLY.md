# GEO 客户只读工作台

前端基于 `codex/production-sem`，按任务目录中的 CONTRACT v1 对接独立 GEO 后端。无需合并后端分支或 SEO 草稿 #768；后端项目读取 PR 提供 `/projects/{project_id}/client/...` 后才能显示真实的新资源。本 PR 不证明接口已经部署。

- 首页本期要点分别来自 overview 的当前待确认库存、executions 的已加载进度、overview 的完整周关注项。内容库存、月度站内任务和上海完整周指标分别标明周期。
- 标签按已读到的资源显示；空内容/交付不显示空标签。首页和站内优化始终保留；原有官网知识建设、站内任务交互、搜索可见度面板继续使用原组件。
- 数据：AI 可见度 → 问题或引擎 → 回答列表 → 保存原文、来源、模型、引用和正式采纳情况。单问题只显示 X/Y 次。指标不足显示“检测数据还不够”；合格真实零值仍显示 0%。支持选择服务端校验的完整周。
- 内容：任务 → 当前母稿 → 渠道稿 → 关联母稿版本；交付：原生发布登记和投递回执分别呈现。客户确认不等于发布，成功回执不等于发布登记，发布登记不等于已有页面匹配证据，存量证据不代表正式客户验收。新增页面没有写操作。
- 新请求仅限契约 A–L 和 executions 的精确 GET 路由、query、当前客户与项目；未知参数、重复参数、请求体、其他项目、旧租户读取入口均拒绝。分页游标只作不透明参数传递。403/401 延续宿主失效处理，旧 scope/revision 的晚到响应不显示。
- 404/405 显示“暂未开放”，不切换租户接口；部分失败不覆盖其他成功模块。分页 400/409 丢弃旧列表与游标并从首屏重读；详情读取失败清除该详情。响应范围、周和详情 ID 不符时拒绝显示。
- 503（包括后端 `GEO_CLIENT_READ_UNAVAILABLE` 读取预算/查询源不可用）显示“数据量较大或读取暂不可用，请稍后再试。”；首页、详情和分页失败均有可见提示，可手动重读，其他标签及原有面板继续可用。错误响应正文不直接显示。
- 进度和服务计划固定读取宿主白名单内的 `executions?tenant_id=…`，不依赖或跟随 `overview.links.executions_path`；旧 executions 响应不套新外壳。按钮参数 JSON 损坏或解析结果不是对象时显示通用提示，不发请求，不吞掉错误。
- 正文作为转义纯文本保留 Markdown 原文，不执行 HTML、不加载图片。可点击引用只限公开 http(s) 且无用户信息、凭据类 query、内部主机或 IP 的链接；保留普通参数并剔除 utm_* 等跟踪参数；服务器仍负责完整的安全 URL 投影。
- executions 只展示客户字段；不显示账号名、顾问 ID、内部 ticket 链接或完整 JSON。20 项任务、200 问题及单项证据截断单独提示，不计算全项目完成率。

本次只改独立工作台和测试，无迁移、无新 env、无后台/部署流程改动，无采样、巡检、生成、确认、发布或重试。原有站内任务权限和写操作保持原实现。

验证全部使用合成宿主和拦截的 HTTPS 域名，不登录真实账号、不连数据库、不访问供应商或生产站点：

```powershell
npm --prefix customer-workbench ci
npm --prefix customer-workbench run test:contracts
npm --prefix customer-workbench run test:geo-client
npm --prefix customer-workbench run test:onsite
npm --prefix customer-workbench run test:search-visibility
node --test customer-workbench/ui15-entry.test.mjs customer-workbench/ui17-entry.test.mjs
```

新单测已接入现有 `test:contracts`，新浏览器测试已接入现有 CI 调用的 `test:onsite`，无需修改 workflow。截图写入本机临时目录，不进入产物。未验证：真实权限/真实数据、生产接口联调和部署验收。

第 2 轮与后端 Draft PR #782 的 `66be297c2134e8eda39bebd0ec2455d718f8e7dc`（phaseLINK 更新） 完成源码字段核对，详见 [A–L 对照表](GEO_CLIENT_ALIGNMENT_R2.md)。`tests/geo-be-response-snapshot.json` 是该提交的内存 SQLite/TestClient 合成 HTTP 输出，共 49 例；契约测试把这些输出交给真实前端校验与视图，CI 不导入后端、不启动应用、不需要数据库或真实配置。快照是固定版本的回归证据，后端字段变化时须重新核对，不能作为生产联调证明。分页合并后的 items 为累计条数，pagination.returned_count 保持最后一个网络页的含义。

phaseLINK 同步前后端参数规则与仅域名降级，详见 [契约变更记录](CONTRACT-ISSUES.md)；合成快照基准以 JSON 的 backend_head 为准。

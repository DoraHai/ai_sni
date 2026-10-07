# UI-10 明确触发、AI草稿授权与人工登记

2026-10-07。仅本地独立工作台，契约基线为 SEO `c8fa621ee3aba71575c5348a8fb116e11f2f6136`。未修改或合入 SEO/SEM 源码，宿主仍沿用 UI-07 的固定基线。

## 已接入的业务流程

### 四类手动触发

服务计划页面分别显示 content、website、monitoring、report 的 `trigger_actions`、拒绝原因、已读 expected_revision 和具体影响。触发资格来自独立 GET 投影，不从 update_service_plan、角色名称或周期开关推导。进入页面仅 GET，点击才 POST：

- 内容：`/api/v1/seo/workbench/service-plan/run`，tenant_id/site_id/expected_revision/request_id。
- 其余三类：`/api/v1/seo/workbench/service-cycles/run`，增加真实 kind。
- 只接受固定 endpoint/method/kind/meaning 和 UUID 格式；成功后重新读取执行详情，不把“建立任务”说成“完成服务”。
- 未知响应保留原 UUID 并关闭同类型新触发；刷新资格不创建新 UUID、不重发。读取执行列表时按同类型 request_key 核对已存在任务。分页之外的记录须继续翻页读取；没有新增查询 UUID 的接口。
- 未知请求编号仅保留在当前页面会话内，不新增认证或长期本地存储。重开页面仍须核对实际进度，服务端另有 UUID 幂等和活动链门禁。

### AI草稿设置和资料选择

`content_ai_enabled` 默认 false。用户明确勾选并保存时才提交 true；没有变更时省略 AI 字段。选择变化且保持开启会同请求明确提交 true，授权人和时间只读取保存结果，前端不提交身份字段。

- `GET /api/v1/seo/qa/facts?tenant_id=&site_id=`：数组，最多最近500条，**没有 total 或分页**。页面明确这个范围，展开可读标题、正文、来源、有效期和版本；停用、过期、正文或来源缺失的资料不能用于开启。历史选择可移除或清空。
- `GET /api/v1/seo/keywords?tenant_id=&site_id=&status=active&page=&page_size=50`：精确同站点分页，跨页保留选择，只使用已读取且验证归属的记录，拒绝 site_id=null 或其他站点。
- 至多20条资料、5个关键词；前端做必要选择检查，服务端最终核对实时有效期、快照及完整50000字符上限。资料列表不是事实真伪认证。
- 使用 `content_ai_policy.can_configure/can_disable`；无关键词权限仍能按 can_disable 明确关闭，不读取关键词或伪造身份。保存时继续带计划 revision；冲突和撤权后重读，不重发。
- 读取资料或翻页保留本次未保存的计划文字/周期选择。未实际读取的历史引用不能用内部 ID 输入绕过检查，可清空重选。
- 执行详情展示 `params.ai_draft` 的真实状态、授权者、保存版本、原因及资料快照。成功仍是 drafting/待内审；没有自动审核、确认、发布或 AI 重试按钮。此批不调用 content-ai/assist 或供应商。

### 人工登记与已有记录回填

顾问还需 delivery 的 assigned advisor、start_publication 和准确 approved 状态；0104 unavailable 不可借登记绕过。

1. 新建 manual 携带打开表单时已展示的 source_version + payload_hash，平台、实际公开链接及北京时间。提交前不会重新读稿并静默替换预期值。
2. 已有 complete 另外要求该条记录 `allowed_actions.complete === true`，准确 action_requirements（固定方法/地址、source_version、record_existing_publication_only），且状态 manual_required/failed/preparing。published/publishing、旧版本或缺资格不开放。
3. 两种表单均需用户勾选“已到平台核对该准确版本发布且链接可访问”。此复选框是操作前的明确确认，不代替后端权限或内容确认。
4. 保存只称“人工登记事实”，不称平台 API 发布成功。响应 `page_verification` 的 queued/existing/not_queued/not_applicable 单独展示，排队不称页面核验通过。保存后 GET 交付稿与记录核对实际结果。
5. 冲突、撤权、缺前置条件428、网络或响应正文中断均不自动重发，旧操作快照清空。结果未知应重新读取记录核对。

执行详情的发布记录选择已由内部 ID 输入框改为同稿件 GET 列表选择；客户端也验证所选 ID 来自当前已读记录。旧编辑器和分发页跳转继续关闭，不假定 SEM 宿主已经更新。SEO 确认旧 PATCH 发布本来就拒绝绕过；UI-09 的兼容性问题不定性为后端漏洞。

## 本批未接入/限制

- 事实资料新建、维护、500条之外的搜索/分页仍无本工作台页面；现有事实读取契约已接，不以手填内部 ID 代替。
- 完整富文本编辑器、AI单次assist、平台真实执行、外部页面核验的真实运行未在本批调用。已有轻改/内审/确认保持 UI-09 流程。
- 页面不会替顾问确认来源真实，不把供应商配置可用等同于本次生成成功。
- 生产后端部署/0105结构、实名顾问、供应商额度和真实平台/页面验收仍由总控安排。本机内存夹具不能替代 PostgreSQL 并发或生产验收。

## 本地验证

`npm run test:ui10` 为6项契约和3项 Edge 页面测试：默认关闭、同站点资料和关键词分页/显式授权、过期/跨范围/撤权、四类独立触发及 revision、未知请求 UUID 保留/只读核对、准确版本 manual/逐记录 complete、0104 unavailable、冲突和未知结果不重发。AI成功页面使用持久化任务夹具，不是真实供应商调用。

实际结果：UI-10 9/9；与连接浏览器及执行客户端合并执行共15/15；既有contracts 28/28；UI-09原字段客户端5/5；UI-06浏览器2/2；本轮UI-08/UI-09浏览器相关流程也通过。分组存在重叠，不叠加为独立用例总数。旧连接测试在DOM已恢复可用时出现等待超时，改为对真实按钮状态显式50ms轮询并保留失败诊断，最终独立及合并执行均通过。桌面资料选择及人工登记截图仅留 TEMP；390像素窄屏检查不横向溢出。测试使用 loopback 假身份及内存 API，无生产令牌、数据库、供应商或采集/发布调用。

构建仍只产生四文件；提交后重建需核对 manifest 的完整 Git SHA、sourceTreeClean=true 和输出哈希。未推送、合并、部署或迁移。

# 工作台按文章查看发布记录

SEO 交付记录与稿件详情、GEO 项目交付记录与任务/渠道稿入口共用只读组件。客户与顾问进入同一模块页；顾问主任务清单和指标不变。

## 接口依赖

- SEO 合同：`codex/dht-merge-seo-backend-20261023`，`158e52cba62fc091c2b610f20cb026227fb4d878`。
- GEO 合同：`codex/dht-merge-geo-backend-20261023`，`388da53d9e14f95f8ec4d4a7cc883ce2b3a0161d`。
- 仅新增工作台 SEO `/api/v1/seo/workbench/publication-groups` 与 GEO `/api/v1/geo/projects/{projectId}/client/publication-groups` 的精确 GET 白名单。
- SEO 必填 tenant_id/site_id，GEO 必填 tenant_id 且项目仅来自路径；其余仅 bucket/article_id/limit/cursor。客户拒 invalid、重复/未知参数、路径别名、内部路由和所有写方法。
- schema=1，source 为 native/external_report。SEO counts native/external/articles/unlinked/loaded、completeness=complete_snapshot、context.revision；GEO counts native_records/external_records/article_groups/unlinked_records/loaded_items、completeness 含 visible_current_master 与 revision。分模块校验后归一统计字段。

文章键严格包含模块、客户、网站/项目、group_article_id；GEO 必须等于 task_id，article_version_id 仅为版本属性。子行只按原生 publication ID 或外部 receipt UUID 去重，同标题/同 URL 保留全部明细。文章、待关联和单篇明细各有独立游标；服务端范围统计不随来源筛选改变。loaded 字段只与本次页长度比较，不代替全范围总数。

同一页面的列表、待关联、明细须保持同一范围 revision；更改/删除/撤权、游标失效或异常 DTO 会清空分页并要求重读。401/403 继续触发宿主清理。503 明确提示读取不完整；继续加载失败保留已授权的旧页供查看并提示刷新，不将失败解释为 0。重新激活页面会读取新状态。

## 原生事实与旧回执

N、E、A、U 均来自新接口，不写入任何原生数组、执行/KPI/报告字段。外部行只显示“操作人报告…”及“正文暂不可核验”。SEO 原生页面证据和登记/尝试入口独立保留；GEO 旧 deliveries 中的 push receipt、原生登记与核验证据维持原含义，不并入 v2 来源。没有 label 按钮或写白名单，没有迁移、模型、报表/PDF/Excel 改动。

安全链接复用现有 GEO 链接隐私策略；禁止危险 scheme、userinfo、敏感 query 和非公开目标。文本转义。链接处理只负责安全展示，不参与文章或发布身份判断。

## 验证与发布

`test:contracts`、`test:geo-client`、`test:advisor`、`test:publication-groups`、`build` 使用合成数据。新增浏览器用例覆盖 SEO/GEO × 客户/顾问、独立分页、待关联、503/403、revision 变化、未选范围及 390×844；网络拦截只允许测试域和本进程 loopback fixture。纯合同测试覆盖 5101 篇和单文 101 条、版本/任务 ID 碰撞、越权参数与迟到响应、原生/旧回执指标不变。

本 PR 仅 Draft；两个后端先完成审核与用户批准的健康检查后再发布工作台。工作台仅在 codex/production-sem 上手动运行 customer-workbench.yml 且 deploy=true 才部署；PR/push 仅构建。回滚静态包至本 PR 前基线 25766aea91f66f86a59937e1de20a51c14b9aeb4；如同时回退后端，先回退工作台。此文档没有授权或执行部署。

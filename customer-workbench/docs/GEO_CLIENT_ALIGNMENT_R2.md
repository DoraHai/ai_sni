# FE–BE 字段对照 r2

日期：2026-10-20；窗口：phaseFE2。后端只读基准为 Draft PR #782 的 `e83206965178e1869cc35fbaabb6d2973def465d`，通过 `gh pr view` 与 `phaseBE/wt` HEAD 双重确认。前端为 Draft PR #781 原 head `95df41e8` 加本轮修订。未合并分支，未修改后端。

核对来源：后端 `app/geo/project_client_protocol.py`（路由、参数、游标）、`project_read_routes.py`（A–L）、`project_client_view.py`（全部白名单投影）、`project_client_store.py`（读取预算），以及 `read_model.period_context`；前端 `geo-client-routes.mjs`、`geo-project-client.mjs`（校验）、`geo-project-panel.mjs`（请求/分页）和 `geo-project-view.mjs`（渲染）。下表记录实际实现，不把前端的结构检查描述成全字段 JSON Schema 校验。

## 记号与公共请求

`P=/api/v1/geo/projects/{project_id}/client`。全部 GET；每条必传 `tenant_id`，path/query ID 为 JS 安全正整数。前端只发送规范十进制 ID；后端也接受有前导零的十进制输入，前端白名单有意更窄，不影响本客户端请求。拒绝重复/未知 query、body、写方法、其他项目和外域路径；后端重新授权，前端白名单不替代权限。

下表 `W=week_end?:YYYY-MM-DD`，A–F 省略时由服务端选择上海时区最近已结束完整周的周一；前端首个成功周响应后固定传该周。日期格式由宿主检查，日历是否合法、是否周一、是否已结束及最小日期由后端 `validated_week_end` 判断。前端不另算默认周。

`Q=limit?:1..100（默认20）,cursor?:非空、不透明、最长4096字符`；前端不解码游标。`q` trim 后 1..100 Unicode 字符，本轮修复 JS UTF-16 长度与 Python 字符数的差异。枚举及布尔筛选均精确匹配，不允许任意数据源/业务参数。

类型：`ID`=安全正整数，`N`=非负整数，`S`=字符串，`B`=布尔，`T?`=UTC Z 时间或 null，`?`=可空；数组无数据为 `[]`。派生计数不从已加载一页重新推算。

## 共用成功外壳、分页和错误

| 字段 | 后端实际类型/空值 | 前端核验和显示 | 结论 |
| --- | --- | --- | --- |
| schema_version / tenant_id / project_id / read_only | `geo.client.v1` / ID / ID / true | 严格比对版本、当前客户项目、只读标志；请求前后核验 context/generation | 一致 |
| evaluated_at | UTC Z 查询时间 S | `geoTime` 转上海显示，无效为“未知”；不用作数据刷新时间 | 一致 |
| scope | ownership_basis=`current_project_binding`，binding_revision=N，binding_state=`bound|unbound`，business_count/question_count=N | 核验 basis 和 state；展示归属、问题数量和空绑定；不以返回 revision 授权 | 一致；revision/count 不做完整 schema 检查 |
| basis | kind=`saved_records`，aggregation_complete=true，last_data_at=T?，period=Period?，source_counts={real,manual,simulated,unknown:N}?，unknown_time_count=N?，unknown_time_scope=S?，exclusion_counts=[{code:S,count:N}]，note_codes=S[] | 核验 kind；显示完整范围说明、来源/时间/排除原因，不累加排除计数充当回答总数；不显示未知 note 原文 | 一致 |
| A–F basis.period | `{timezone:Asia/Shanghai,week_end:S,start:S(+08:00),end:S(+08:00),closed:true}` | 严格核验 week_end 格式、请求周相等、上海时区、closed；显示起止和右端不含 | 一致 |
| G–L basis.period/source_counts/unknown_time_count/unknown_time_scope | 均 null | 无来源/周块；显示当前归属的已存历史。旧手写 fixture 的时间字段已改 null | 一致 |
| F unknown_time_scope / unknown_time_count | `single_answer` / 0或1，last_data_at 为本条 captured_at，可为 null | 显示“本条回答”；其余 A–E 为 current_project_history | 一致；实际 null 回答已测试 |
| C/E/G/I/L data.pagination | `{limit:N,returned_count:N,total_count:N,has_more:B,next_cursor:S?,truncated:B}`；returned_count 为本页条数；total_count 为筛选+首屏水位内全量；has_more=truncated | 校验 items 数=returned_count、total_count 合法、两个布尔、游标/结束页一致性；不重排 items | 一致 |
| 前端多页合并状态 | 后端每页仍返回自己的 pagination 和 basis | 合并 items，保留最后一页 pagination；显示 items.length/total_count；增加明确注释，returned_count 不作累计数量 | 一致；非独立网络响应，不再次送入单页校验 |
| 游标 | 后端绑定资源、客户项目、规范化筛选（含limit/周）、父task、revision/归属链、水位和排序键 | 原样转交 next_cursor；400/409 丢弃旧列表/游标并重读首屏；晚到页丢弃 | 一致；五类实际分页已离线验证 |
| 400 INVALID_WEEK / INVALID_CURSOR | `{detail:{code:GEO_CLIENT_…,message:S}}` | 不展示原文；无游标的周查询提示有效完整周，有游标则清分页重读 | 一致；使用状态和请求语境做安全映射 |
| 401 / 403（认证、FORBIDDEN、MODULE_UNAVAILABLE、DEMO_UNSUPPORTED） | 新 detail 或原认证 detail | 宿主使当前授权失效；401 沿用失效/登录跳转；不展示旧数据、无其他客户兜底 | 保持既有行为 |
| 404 NOT_FOUND / 405 | 项目/对象不存在或未开放；405 为框架形状 | 对当前资源显示“暂未开放”，不探测其他对象或租户接口 | 一致 |
| 409 PROJECT_INACTIVE / BINDING_INVALID / SCOPE_CHANGED | 客户可读错误 | 安全归一为 GEO_SCOPE_CHANGED；分页只重读一次首屏，失败仍留可见错误；不修绑定、不写数据 | 可兼容的状态兜底，未细分内部 code |
| 422 INVALID_QUERY / 原框架错误 | 拒绝非法 ID、筛选、body 等 | 通用读取失败，不透传 detail | 一致 |
| 503 READ_UNAVAILABLE | 预算或查询源不可用；不返回伪完整统计 | 本轮映射 GEO_READ_UNAVAILABLE，显示“数据量较大或读取暂不可用，请稍后再试。”并允许手动重读；不代触发检测 | 已修改；首页、详情、分页局部失败和其他面板保持独立 |

## A–L 路由矩阵

每条都使用上述公共外壳和错误表；下列是完整 `data` 字段清单，复用类型在下一节展开。

| 编号 / 实际路径 | 额外 query（不含必传 tenant_id） | 后端 data、类型和空值 | geo-project-client 校验 / view 渲染 | 结论 |
| --- | --- | --- | --- | --- |
| A `P/overview` | W | project={id:ID,name:S,brand_name:S?,canonical_domain:S}；content={time_basis:current_inventory,active_task_count,pending_review_count,approved_current_master_count,task_count_with_master,variant_count,native_published_record_count:N}；monitoring={time_basis:closed_week,active_nonbrand_question_count,attention_question_count,no_real_observation_question_count,some_nonmention_question_count,observed_question_count,saved_answer_count,qualified_answer_count:N,latest_answer_at:T?}；weekly=Weekly；links={pending_content_path,questions_path,attention_questions_path,visibility_path,deliveries_path,executions_path:S} | 核验 content/monitoring/weekly 是对象；首页取库存/待确认/监测关注和完整周；各自依据独立。links 不执行，全部跳转由资源名/ID构造 | 字段一致；overview 503 有明确提示；不依赖 executions_path |
| B `P/visibility` | W | current/previous=Weekly；comparison={comparable:B,checks:{current_week_sufficient,previous_week_sufficient,same_cohort,same_historical_questions,complete_model_metadata,same_model_distribution,same_sample_distribution:B},reason_codes:S[]}；engines=Engine[]（含 qualified_question_count:N）；definitions={mention_count,mention_rate,visibility_score,qualification,ownership_basis:S} | 检查 current/previous/comparison 对象、engines 数组；展示 current 和五项静态说明、可比时趋势、引擎观测和回答入口。previous/checks 用于判断背景，不重算趋势 | 一致 |
| C `P/questions` | W+Q；status=all/active/inactive/archived（默认all）；is_brand_probe?=true/false；attention=all/needs_attention（默认all）；q? | items=Question[]，pagination；filters={status:S,is_brand_probe:B?,attention:S,q:S?} | 校验标准页；显示问题/状态/品牌题/Observation/关注原因；ID→D，后端筛选参数原样转交 | 一致；q Unicode 上限已修复 |
| D `P/questions/{question_id}` | W | question=Question；by_engine=Engine[]（无 qualified_question_count）；evidence={answer_count,excluded_answer_count,unknown_time_count:N,unknown_time_scope:current_project_history}；answers_path/content_path:S | 核验 question.id 等于路径 ID、by_engine 数组；展示 X/Y、各引擎、本周去重回答数和当前问题历史未知时间数；重构 E/G 请求，G 不带 week_end | 一致；无周回答仍为200/0次 |
| E `P/answers` | W+Q；question_id?:ID；engine_key?:1..64 `[A-Za-z0-9_.-]`；source_kind?=real/manual/simulated/unknown；eligibility=all/qualified/excluded（默认all） | items=Answer[]，pagination；filters={question_id:ID?,engine_key:S?,source_kind:S?,eligibility:S} | 标准页；显示来源/历史提问和模型/单条资格/周成员/采纳情况/节选；回答ID→F，不用 rows.length 计算指标 | 一致；周内 captured_at DESC（微秒）、id DESC 由服务端完成 |
| F `P/answers/{answer_id}` | W | item=Answer；raw_text:S；citations=[{url:S?,url_state:available/suppressed/invalid,is_own_domain:B}]；comparison_metadata={complete:B,reason_codes:S[],model_identity_basis:recorded_request_model_alias或null,exact_model_revision_known:false} | 核验 item.id、完整 raw_text 字符串、citations 数组；纯文本全文、三态提及、来源和资格、模型缺失原因、自有域标签；被抑制 URL 不点击 | 一致；周外/无时间 detail 正常200，状态及采纳不冒充周内 |
| G `P/content` | Q；question_id?:ID；review_status?=none/pending/approved/rejected/unknown；include_archived=true/false（默认false）；q? | items=Content[]，pagination；filters={question_id:ID?,review_status:S?,include_archived:B,q:S?} | 标准页；状态、Review、latest_master、渠道稿/发布计数和H入口。后端按question过滤，不对已加载页假筛选 | 一致；补齐 facts_bound/needs_fix/adapting 标签；q Unicode 同步 |
| H `P/content/{task_id}` | 无 | task=Content；master=Article?；variants_path/deliveries_path:S；receipt_summary={succeeded,failed,unknown,sending,other:N} | 核验 task.id；master=null 或 task_id 同父task；展示确认覆盖/全文/回执分类；重构I/L，确认不等于发布 | 一致 |
| I `P/content/{task_id}/variants` | Q | items=Variant[]；pagination | 标准页；展示渠道、母稿版本、是否当前母稿、状态；ID→J；不重排 ID DESC | 一致；实际两份渠道稿limit=1验证分页 |
| J `P/content/{task_id}/variants/{variant_id}` | 无 | variant=Variant；body_markdown:S；article_path/deliveries_path:S | 核验 variant.id/task_id；全文纯文本；以 variant.article_id/task_id 构造K/L | 一致；无 HTML/adapt_meta 或发布动作 |
| K `P/content/{task_id}/articles/{article_id}` | 无 | article=Article；is_current_master:B | 核验 article.id/task_id；显示当前/历史母稿、版本和完整正文 | 一致 |
| L `P/deliveries` | Q；task_id?:ID；record_type=all/publication/receipt（默认all） | items=(Publication或Receipt)[]；pagination；filters={task_id:ID?,record_type:S}；counts={publication_records,receipt_records,published_records,stored_verified_publications:N} | 标准页；publication/receipt分别渲染；公布URL需available并再过geoSafeLink；核验、确认和发布不合并。receipt 的 article_id 可空，不据它生成母稿入口 | 一致；修正 verification.pending 为“待页面核验”；顺序保持后端先publication、后receipt |

## 复用行类型逐字段核对

| 类型 | 后端字段及类型/空值（完整白名单） | 前端消费情况 |
| --- | --- | --- |
| Weekly | week_end:S；period={timezone:S,start:S,end:S,closed:B}（此内层无week_end）；sample_status=ready/insufficient；message:S?；qualified_counts/minimum_counts={samples,questions,engines:N}；reason_codes:S[]；own_domain_configured:B；own_domains:S[]；qualified_mention_count/qualified_own_domain_citation_count:N；metrics=Metric[] | 正式展示由 sample_status、metrics 决定；message不透传，固定不足文案。coverage显示qualified_counts，8/3/2固定口径；own_domains/描述性分子不另造KPI。旧fixture补message |
| Metric | key=geo.visibility.ai_mention_count_7d / ai_mention_rate_7d / ai_visibility_score（三个完整前缀key）；unit=count/percent/score；value=number?；status=available/insufficient/unavailable；reason_codes:S[]；trend_7d={direction:up/down/flat,change_abs:number,change_pct:number?}? | 仅available且value有限才显示值，保留真0；不足不格式化null为0%；可比且有trend才显示变化；未用change_pct反推增长 |
| Observation | mentioned/total:N；status=observed/no_observations；display_text:S；basis_code=saved_real_analyzed_answers；official_question_rate=null | 静态拼接X/Y次/无观测，不显示正式问题百分比，不执行服务端display_text |
| Engine | engine_key:S；observation:Observation；qualified_sample_count:N；仅B另有qualified_question_count:N | 展示key/观测/样本；向E传engine_key，不把引擎观测当正式引擎百分比 |
| Question | id:ID；question:S；status=active/inactive/archived/unknown；is_brand_probe:B；business/unit={id:ID,name:S}；observation:Observation；qualified_sample_count:N；latest_answer_at:T?；attention_reason_codes:S[]；detail_path:S | 显示已知状态/题目/观测/关注；business/unit/派生链接未扩展展示；不把unknown当active |
| Answer | id/question_id:ID；question={historical_text:S?,current_text:S,historical_text_source:patrol_item或null}；engine={key:S,provider:S?,model:S?,model_revision:null,metadata_source:patrol_item或null}；captured_at:T?；captured_at_local:上海偏移时间S?；time_basis=stored_utc/unknown；source={kind:real/manual/simulated/unknown,sampling_method:unprimed_json_v2/legacy/unknown,analysis_status:completed/needs_review/unknown,verified_server_record:B}；answer_excerpt:S（≤300 Unicode字符）；excerpt_truncated:B；mentions_brand:B?；sample_eligibility={eligible:B,reason_codes:S[]}；week_membership={within_window:B,included_in_cohort:B,reason_codes:S[]}；metric_adoption=[{key:三个指标key,status:included/excluded/unavailable,reason_codes:S[]}]；detail_path:S | 显示历史文字优先、模型/来源/采纳/资格及真实时间；精确版本明确未知；null提及显示未知；captured_at_local/time_basis/metadata来源等保留但不输出内部JSON；详情ID核验；不把verified_server_record单项当成整周成立 |
| Review | status=none/pending/approved/rejected/unknown；reviewed_at:T?；covers_current_master:B；display_text:S | 静态标签；approved但不覆盖显示“历史版本已确认，当前版本尚无有效确认记录”；不从发布反推确认 |
| Content | id/question_id:ID；title/question:S；stored_status=draft/facts_bound/generating/editing/needs_fix/adapting/ready/exported/published/failed/archived/cancelled/unknown；pipeline_step=opportunity/evidence/draft/adapt/publish/unknown；review:Review；latest_master={id:ID,version_no:N,title:S,created_at:T?}?；variant_count/published_record_count:N；updated_at:T?；detail_path:S | 使用title/status/review/current version和计数；pipeline不当进度比例；未读的公开字段不产生额外动作 |
| Article | id/task_id:ID；version_no:N；kind=master；title/body_markdown:S；created_at:T?（投影iso支持null，正常模型为已保存时间） | task/id父子核验，正文转义进pre；缺正文是空串，不重新生成；master为空有提示 |
| Variant | id/task_id/article_id:ID；article_version_no:N；channel/title:S；stored_status=draft/exported/published/unknown；created_at/updated_at:T?；is_current_master:B；detail_path:S | 版本/渠道/当前或历史母稿/状态；J使用全文，不拿列表当正文；未知渠道“其他渠道” |
| Publication | record_type=publication；id/task_id/variant_id/article_id:ID；article_version_no:N；is_current_master:B；title/channel:S；publish_mode=manual_export/api/browser/unknown；stored_status=pending/published/failed/unknown；published_url:S?；url_state=available/suppressed/invalid/missing；published_at/updated_at:T?；verification={state:pending/healthy/unverified/unhealthy/unknown,checked_at:T?,evidence_valid:B,reason_codes:S[]}；task_path/variant_path/article_path:S | 只有available的公开URL才再经前端链接策略；展示核验证据/时间/原因，pending明确“待页面核验”；不把publish_mode、published或健康状态单项升级为验收 |
| Receipt | record_type=receipt；receipt_id:S（不透明摘要）；task_id/variant_id:ID；article_id:ID?；article_version_no:N?；is_current_master:B；title/channel:S；state=sending/succeeded/failed/unknown；updated_at:T?；reason_code:S?；display_text:S；task_path/variant_path:S | 仅展示安全状态/原因和task/variant入口；不沿空或未知article读取；成功回执不等于发布；不解析receipt_id |

URL 规则双方一致：仅公开 http(s)、无userinfo/query/IP/内部域、端口限80/443、剔除fragment；后端带query引用返回url=null/url_state=suppressed，但仍按原host标记is_own_domain，前端直接采用该标记。`geoSafeLink` 对少量主机名继续更保守（例如localdomain），不放宽后端。正文按纯文本转义，不执行HTML或自动取图。

## 证据与处理记录

1. 后端实际响应快照：前端仓库 `customer-workbench/tests/geo-be-response-snapshot.json`，45例，包含全部12路由、五类limit=1分页与末页、筛选空页、完整周不足/合格真0、单回答null时间、400/404/503。通过后端现有 `tests/test_geo_project_client.py` 的内存 SQLite/TestClient 导出；依赖使用合成 Settings.model_construct，禁外部socket/asyncpg连接，未启动应用/调度器，未读取dotenv。导出脚本只放TEMP，后端工作区保持原状。
2. `geo-project-client.test.mjs` 逐例把实际后端响应送入客户端校验和视图渲染；全部成功响应被接受，失败映射安全错误。另测100/101个非BMP字符搜索、损坏JSON/非对象参数、恶意executions_path、503隔离、状态文案和晚到/换周分页。
3. 新浏览器场景：A–L全部503但executions正常，首页和详情可见错误、重读按钮、进度/计划仍可读；原站内、官网知识建设、搜索面板保留；手机无横向溢出。损坏data-params有role=alert且不发请求。
4. 发现并修复的前端差异：q字符计数、三种合法内容状态标签、verification.pending文案；手写fixture补message、filters及G–L可空basis时间字段。分页合并口径用注释明确。格式化为独立提交47dae092，7文件的esbuild压缩输出逐字相同。
5. 本轮未发现需要修改后端或契约的阻断字段差异；未改后端、CONTRACT或新增契约问题。周选择继续依赖服务端语义校验，UI可见提示已有；完整Tab键盘ARIA增强属于后续，不在本轮承诺。没有真实账号/生产接口联调、隔离PostgreSQL或部署验收；这些证据不得由合成快照替代。

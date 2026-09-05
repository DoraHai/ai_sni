# GEO 经营驾驶舱基础设施

本实现只提供模块接口，不连接驾驶舱、不发送外部业务请求。

## 共享字段：保持用户最新契约
Task 返回字段严格为 id、module、action_type、title、params、status、created_by、assignee_role、completion_evidence、created_at、updated_at。
Metric 返回字段严格为 metric_key、value、unit、as_of、trend_7d。

trend_7d 为 null 或以下对象：
```json
{"direction":"up","change_pct":50.0,"change_abs":2}
```
direction 为 up/down/flat/null，仅事实方向，不评价好坏。change_pct=(本期值−前期值)/abs(前期值)×100，change_abs=本期值−前期值。可算时都填；前期为0时 change_pct=null，绝对变化及方向保留；无合格前期数据时整个对象为null，不能用0冒充未知。问题/引擎样本集合不一致时也不形成趋势。

按用户确认，周窗口采用 Asia/Shanghai 最近一个完整自然周 [周一00:00, 下周一00:00)，as_of 为窗口结束时刻。trend_7d 比较前移7天的完整周。日期参数 week_end 必须是周一且不晚于本周周一；窗口参数是查询参数，不增加指标对象字段。
用户同步的 SEO 图片口径同时留档：approved 只表示草稿审核通过，须进入待核实，复用 seo_crawler + save_page_snapshot 定向重抓确认实际修复后才计入完成。本轮没有修改 SEO。

## 接口
路径均以 /api/v1/geo/integration 开头，使用现有认证，tenant_id 必传。读取需要 geo.content 查看权限，写入需要编辑权限，跨租户拒绝。

| 方法 | 路径 | 含义 |
|---|---|---|
| GET | /metrics/snapshot?tenant_id=7&week_end=2026-08-31 | 五字段指标列表；纯读取，不重建缓存、不提交事务 |
| GET | /metrics/dictionary?tenant_id=7&week_end=2026-08-31 | metric_key 到一句话口径文档的映射，含同期竞品名称 |
| POST | /tasks?tenant_id=7 | 创建统一任务，返回201 |
| GET | /tasks?tenant_id=7 | 查询；支持 status、after_id、limit（1–200） |
| GET | /tasks/{id}?tenant_id=7 | 读取任务和完成证据 |
| PATCH | /tasks/{id}?tenant_id=7 | 提交目标状态，done 由服务端验证真实指标 |
| POST | /tasks/{id}/baseline?tenant_id=7 | 仅在原基线缺数据时补采基线；有效基线不可覆盖 |

响应模型已进入 OpenAPI，可从现有 /openapi.json 查看 MetricSnapshot、MetricTrend、TaskContract。

创建示例：
```json
{
  "module":"geo",
  "action_type":"improve_content",
  "title":"补齐选型问题的品牌事实与来源",
  "params":{"metric_key":"geo.visibility.ai_mention_count_7d","direction":"increase","min_delta":2},
  "status":"open",
  "assignee_role":"geo_operator"
}
```
created_by 从认证身份推导，用户为真实user_id，服务API密钥为cockpit；提交不同身份返回403。params.metric_key 默认提及次数；direction 为 increase/decrease，默认 increase；min_delta 默认为0，但完成仍须严格正向变化，不能零变化完成。assignee_role 是执行角色标签，不授予权限。

## 指标字典与可比性
- geo.visibility.ai_mention_count_7d：合格回答中 mentions_brand=true 的条数，一条回答最多计1次，unit=count。
- geo.visibility.ai_mention_rate_7d：品牌提及回答数/全部合格回答数×100，unit=percent。
- geo.visibility.ai_visibility_score：50×品牌提及率+50×自有域引用率（两率为0–1），unit=score，范围0–100。引用分母为全部合格回答，一条回答有多个自有域链接仍计1次；自有域来自启用的 website/docs 渠道及其子域；没有配置时综合分为null。该分数不是网站诊断分或正文质量分。
- geo.competitor.{名称哈希}_mention_count_7d：同一批回答中该竞品出现的回答条数，unit=count。名称strip/casefold后SHA256前20位作为稳定key，单条回答去重。字典返回原归一名称。任务基线已记录的竞品会继续保留，即使近两周没有命中也能显示已观测到的0。

合格集合：同一租户、非品牌点名问题、真实v2 API、判读完成且引用未标为错误；还必须匹配已完成服务端巡检保存的原始结果（原文、问题、引擎、提及、竞品、引用及巡检时间范围）。手工贴入的“API采样”标签不足以进入驾驶舱统计。未被服务端巡检追溯的单次手工确认探测也暂不纳入。
每周至少8条、3个问题、2个引擎，否则各指标value=null；无样本不伪造0。上述数值是有限采样结果，不是全网统计，也不证明任务造成因果改善。名称别名除大小写与首尾空格外不自动合并。

## 任务如何复用原工单
复用 geo_action_tickets，无新表、无结构迁移。advice_code=cockpit:v1:task，progress_first 保存契约元数据，baseline_snapshot 保存服务端基线，progress 保存服务端完成证据。
状态映射：todo→open，doing→in_progress，done→done，cancelled→cancelled。该适配入口只管理通过统一接口创建的工单；历史人工验收工单不伪装成具备真实指标证据的任务。原有工作队列和诊断工单保留原流程。

完成条件：
1. 同一任务加行锁，完成/取消为终态，重复提交同状态幂等返回。
2. 后测是任务创建之后的完整自然周，且晚于基线。
3. 指标前后均非null，问题×引擎集合、每个组合的采样次数及自有域配置一致，避免增加采样量或改变样本权重被当成任务效果。
4. 达到指定方向和最小变化量。
5. 服务端生成包含前后指标、delta、快照ID、核验时间和带租户/周参数的指标来源地址；客户端不能提交 completion_evidence。
旧 action-tickets 创建/人工验收入口拒绝冒充或改写这些统一任务。没有合格数据的任务保持未完成，可补采一次有效基线后继续。

## 审查问题修复
- 竞品对比在聚合前过滤不合格样本及品牌点名题，样本不足不再输出胜负或竞品百分比。
- 日聚合不再截断15个竞品；竞品日接口从合格原始快照只读重算，绕开旧缓存截断。
- 网站抓取连接绑定已校验公网IP，保留原Host和TLS SNI，禁用环境代理和跨请求连接复用，重定向逐跳验证。
- robots 区分整站拦截、局部限制及特定UA空规则；保留局部限制统计，不将其算整站拦截。
- 索引判断汇总robots meta，识别none及X-Robots-Tag。
- 报告编辑撤销旧确认；完整版本证据保存在既有JSON字段，恢复文本和证据一起恢复为草稿。旧版本没有完整证据时拒绝恢复，避免拼接最新证据。

robots标准参考：https://www.rfc-editor.org/rfc/rfc9309.html 。索引指令参考：https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag 。固定IP同时保留SNI的实现依据：https://www.encode.io/httpcore/extensions/#sni_hostname 。

## 验证边界
有模拟会话的路由/锁顺序测试、HTTP契约与权限测试、样本来源一致性测试、DNS固定和重定向阻断测试；实际HTTPS抓取example.com成功。未进行内网攻击或生产写入验收。指标读取不会自动重算或写入缓存。

最终本地验收：626项后端测试、62项前端测试通过，GEO独立生产构建与git diff --check通过；测试没有调用真实AI模型或写入生产业务数据。

## 二次审查修复
- direction 传入数组或对象时返回参数校验错误，避免触发500；过早的week_end在查询前拒绝，避免日期运算下溢。
- 完成证据增加前后各问题×引擎采样次数，要求分布一致；旧基线缺少该记录时拒绝完成，需新建任务采集可验证基线。
- 指标快照仍按实际回答条数统计；上述采样分布约束用于任务验收，不改变共享指标公式或trend_7d格式。
二次审查验收：637项后端测试通过，git diff --check通过；本轮未修改前端及SEM/SEO代码。


## 精确复测与发布核验（2026-09-05）

共享任务11字段、指标5字段保持不变。辅助执行接口位于同一 `/api/v1/geo/integration` 前缀，均要求认证及 tenant_id：

- `GET /tasks/{id}/execution-readiness`：只读返回基线阻塞原因、可复测计划、发布账号能力、已核实发布证据和完成证据。不会创建默认渠道或写缓存。
- `GET /tasks/{id}/retest-plan`：从已冻结有效基线复制问题原文、每个问题×引擎的实际次数；不启动AI调用。
- `POST /tasks/{id}/retest`：202返回run_id。必须处于基线结束、任务创建及关联内容首次发布核验之后的完整上海自然周；当周已有样本、在途任务或复测预约时拒绝追加。重复同任务同周请求返回原run_id，不产生新调用。
- `POST /tasks/{id}/publication-check`，正文 `{"publication_id":123}`：重新安全抓取当前版本的真实发布URL，检查标题与至少3段、80%以上的正文片段；保存内容哈希、发布/版本ID及首次和最近核验时间。仅有published标记、标题或隐藏正文不通过。失败不生成完成证据。

创建内容优化任务时，params.content_task_id 可绑定本租户内容任务。完成时重新核验发布页，后测整周必须晚于首次核验；正文版本或URL变化会重新开始核验时钟。HTML匹配并不证明浏览器渲染、搜索收录或AI已经引用。

精确复测最多200个单元，不填充缺失组合、不在失败后偷偷加样本、不回退模拟引擎。失败预约保留，本周不会自动重启或补齐从而偏移样本权重；下个满足条件的自然周可再次启动。执行结果列出缺失单元，未持久化/判读未完成的回答不能计入合格复测。

趋势新增可比性限制：问题原文、问题×引擎及各组合的样本次数须一致，否则trend_7d=null。完成时还重新读取基线来源，基线快照ID、分布、问题、域名或指标被更正时拒绝沿用旧证据。历史基线缺少问题原文不能推测补写，需新建任务采集可追溯基线。

本轮验收：668项本地后端测试、62项前端测试通过；当前代码在真实PostgreSQL独立临时schema完成3项并发终态测试，测试schema已清理。未修改SEM/SEO代码或运行数据库迁移。详细范围、修复和剩余限制见 GEO_DETAILED_REVIEW_20260905.md。

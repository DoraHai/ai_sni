# DeepSeek 搜索可见度（PR1 后端）

只记录搜索引擎的收录、词排名和页面存活；不代表 AI 回答会提及或引用客户。
不改 SEM、现有回答指标、巡检或报告。没有新表、字段、迁移或依赖。

## 配置和权限

使用已有 `geo_projects.project_settings.deepseek_visibility`，默认关闭，客户可见默认关闭。
顾问使用既有 `geo.assets=edit` 和 `geo.content=edit` 权限组合；超管使用全局账号及账号/客户管理权限。
每个接口同时检查租户与 GEO 服务资格；客户不能配置或运行。客户关闭可见时，概览、明细和 CSV
均只返回 `state=not_open,message=暂未开放`。通用异步作业接口不暴露本类任务。
统一菜单门禁对本功能的精确路径承认上述全局超管组合，避免仅有GEO查看菜单的超管被写菜单误拦；
不扩大其他GEO项目、其他模块或SEM权限，租户隔离与接口自己的顾问/超管检查继续执行。

环境变量 `DEEPSEEK_SEARCH_API_KEY` 独立于 SEM，默认空。缺少时显示“待启用”，不影响启动。
其他设置：`DEEPSEEK_SEARCH_BASE_URL=https://api.deepseek.com`（只允许官方 HTTPS 源），
`DEEPSEEK_SEARCH_MONTHLY_LIMIT_CNY=30`、`DEEPSEEK_SEARCH_RUN_REQUEST_LIMIT=60`、
`DEEPSEEK_SEARCH_QPS=4`；可以降低限额，不超过本轮批准上限。

## 接口

前缀 `/api/v1/geo`；项目接口均要求 `tenant_id` 查询参数：

| 方法 | 路径 | 内容 |
|---|---|---|
| GET/PUT | `/projects/{id}/search-visibility/config` | 完整配置、启用状态；读取另含优化单元推荐词 |
| POST | `/projects/{id}/search-visibility/run` | 排队，202；项目北京时间每日最多一次手动运行 |
| GET | `/projects/{id}/search-visibility` | 最近一次、最近12周汇总、固定口径说明 |
| GET | `/projects/{id}/search-visibility/runs/{job_id}` | 项目内单次明细 |
| GET | `/projects/{id}/search-visibility/runs/{job_id}/csv` | UTF-8 BOM、中文表头、表格公式注入防护 |
| GET | `/search-visibility/usage` | 仅超管：全平台本月请求、计费、估算费用、保守预留、上限 |

配置包括 enabled、domains（最多3）、zh_url、brand_terms（最多5）、core_terms（最多20）、
extra_article_urls（最多20）、customer_visible。搜索词最多128字符；URL 仅支持公开 http(s) 页面，
不允许用户密码、内网字面地址或特殊端口。默认从项目域名、中文地址、品牌名及客户品牌词带入。
自动发布链接经 publication→variant→task 限定租户，与媒体布局和补充链接去重后最多20篇。
文章匹配保留查询参数，避免把同一媒体不同文章误认为命中。
现有优化单元没有项目关联字段，因此推荐词明确为同一租户级别，由顾问选择后保存到当前项目。
`index_query_ok` 单列查询完整性；已找到的收录证据不会因另一个域名查询失败而抹去。
外语页面仍可算“可访问”（按批准方案不算失败），兜底的标题、字数、语言分别记录；
`effective_*` 字段表示兜底证据，原 DeepSeek 外语标记保留，避免误称 DeepSeek 返回了中文。

## 执行和费用

周一06:00北京时间由既有 GEO 调度锁的持有进程运行，项目顺序执行、间隔2分钟。
项目同一 ISO 周已有成功记录则跳过。项目行锁保证手动每日及在途任务去重。
独立 PostgreSQL 会话锁串行执行所有本类任务及预算检查；等待锁不占用连接池连接。
调度器每分钟接续已排队任务；中断的 running 任务取得独占锁后记失败，保留费用，不重复请求。

先估算整次请求，再检查余额；每次请求（包括重试）都重新检查单次/月度限额。
余额查询计请求数、不计收费次数。每个潜在收费请求先提交0.005元预留，响应明确后按官方成功口径结算；
连接中断或格式异常结果保守保留预留，单列显示，不冒充已确认费用。此预留会占用当月预算，
没有自动清除或人工改账入口。服务端以北京时间自然月分别记录每次请求，跨月不混算。

全进程最多4次/秒，同网站 fetch 最多1次/秒。连接中断、超时、408/429/5xx 最多重试两次，
间隔2秒、5秒；其他4xx不重试；402立即停止。失败时仅保存安全中文原因，不保存供应商原始错误。
知乎跳过并注明；中文比例过低则标记外语版，调用现有带逐跳公网校验的 safe_fetch 兜底一次。
正文不入库，只保存标题、字数、状态、来源等证据；搜索结果不保存摘要和正文。

官方响应结构依据：[Search & Fetch 文档](https://api-docs.deepseek.com/zh-cn/guides/search)，
2026-10-18核对；Search 为 results 数组，Fetch 为 title/content，正文为 Markdown。
费用按本轮批准的0.005元/成功请求估算；真实账单及正式开通验收属于后续工作。

## 验证、上线与回退

测试全部使用 MockTransport/替身；原生并发测试只连接显式指定的本机隔离数据库，随机schema，
仅建立合成测试表，结束删除；不执行迁移、不读取业务数据。CI独立运行4项原生并发/持久化用例，强制零跳过。

此PR只开草稿，不合并、不部署、不触发工作流。后续须先审核/上线后端，再上线前端。
用户批准上线时在共享 .env 增加上述独立密钥变量并重启 GEO；其他代理保管密钥。
代码不按客户名写死开关；SNIPERS和诺德由获授权顾问在项目设置中开启，前四周客户不可见。
回退本次提交即可，无数据库结构变化；保留 geo_async_jobs 中已记录的费用证据。

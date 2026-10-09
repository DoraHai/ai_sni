# API 费用计量启用审核

本次新增 `api_usage_events` 一张独立台账表及三个时间索引。审核对象：
[`scripts/api_metering_schema.sql`](../scripts/api_metering_schema.sql)。
不修改客户、账号、权限、现有业务表或 Alembic 版本，不补录旧账。
SQL 使用事务、3 秒锁等待和 15 秒执行超时；已在独立 PostgreSQL 测试 schema 执行并验证并发计量。

每次真实服务商请求先独立提交台账，再调用原 HTTP 客户端，然后保存供应商返回用量。
业务回滚不删除已发生调用；每次重试单独计量。台账不可写时拒绝新增付费请求。
进程中断、未返回用量、未配置单价保留为金额未知。模拟、规则与本地缓存没有外部请求时不计量。

归属来自现有认证与服务器授权客户范围。GEO 作业和巡检采用数据库中的客户及创建人；
无登录用户的自动任务、无客户范围的调用分别汇总。新增账号自动进入超管清单；停用账号仍展示。
台账不存储 API Key、令牌、提示词、对话、响应正文或完整含查询参数的 URL。

审核通过后：在生产数据库执行一次此 SQL，依次发布三个独立后端和工作台，
由现有对象所有者执行 `scripts/api_metering_permissions.sql`，只授予运行角色本台账 SELECT/INSERT/UPDATE，
显式撤销默认权限可能带来的 DELETE/TRUNCATE；不授予运行角色建表能力。
并在 SEM、SEO、GEO 服务环境设置 `API_METERING_ENABLED=true`；保持现有其他配置。
这一步必须遵守仓库 AGENTS.md“数据库迁移已经过人工审核”的要求。
上线核验只读取台账与健康状态，不为测试额外发起付费模型请求。
停用使用 `API_METERING_ENABLED=false` 并按既有服务重启流程操作；保留台账和价格版本，避免丢账。

## 初始覆盖

- SEM：JSON 与多轮 AI 客户端、百度营销原客户端；日常洞察与调价复核包含客户归属。
- SEO：JSON 与多轮 AI 客户端、站长之家排名/Top50/域名指标、DataForSEO SERP；租户采集包含客户归属。
- GEO：JSON 与多轮 AI 客户端、引擎采样、异步稿件/渠道版本、巡检、站长之家域名指标。

## 价格口径

金额是人民币原价估算，不声称是服务商实际扣款，不做自动汇率换算。
截至 2026-10-10 核对的百炼北京实时价：`deepseek-v4-flash` 输入 1 / 输出 2 元每百万 Token；
`qwen3.8-max` 输入 12 / 输出 36 元每百万 Token。
来源：https://help.aliyun.com/zh/model-studio/model-pricing
按精确域名和模型匹配，版本 `aliyun-cn-list-20261010` 随每条请求冻结保存。
未提供缓存计费规则的缓存请求暂不估价；不同地域、其他模型与按次接口保留待定价。
支持服务器 `API_METERING_RATES_JSON` 配置合同价，覆盖默认价格表。
Token 示例：`[{"host":"provider.example","model":"model-id","input":"2","output":"4","cached":"0.2","max_input":1000000,"version":"contract-20261010","currency":"CNY"}]`。
按次示例：`[{"host":"provider.example","model":"provider.example/api/query","unit":"request","per_request":"0.01","version":"contract-20261010","currency":"CNY"}]`。
价格配置仅在服务器处理，普通客户无法读取或修改。改价不回写已经计量的金额。

客户汇总与用户汇总是同一份费用的不同维度，不能相加。汇总含未定价请求时不把已定价小计冒充总费用。

# Unknown 调用并发占用修复（2026-10-11）

共享补丁在 `3347b111d65d2f3e07211fcb0d1a0c00de4b70c2` 后取入。
只涉及共享准入、隔离测试与本说明，不含 SEM 监控、路由或生产开关。

`active_calls` 表示全部历史中 `requested + unknown` 的保守并发占用。
HTTP 超时、断连或未获得响应，不能证明供应商任务已经结束；即使不配置金额预算，也保留并发位。
日/月切换、进程退出、告警标记处理不释放占用。unknown 即使后来有金额，结果未确认也继续占用。
收到明确 HTTP 成功或失败响应且提交终态后结束并发占用；金额未知仍单独阻断金额策略。
当前没有人工核实结算入口，需后续独立审核；不能把告警处理当结算或强制释放。

`tests/test_platform_call_guards.py` 新增 8 个原生 PostgreSQL 用例：
全球、客户、用户、供应商四范围各验证超时 unknown 后无金额策略仍拒绝下一次调用、
跨月不释放、独立连接池一致、切换 SEM/SEO/GEO 作用域、非相关范围不误拦截，
以及明确 HTTP 400 终态释放并发。
原 unknown 金额测试移除并发限制，明确断言 `api_charge_unresolved`，避免用并发拒绝掩盖金额验证。
全部供应商请求使用 `httpx.MockTransport`；没有付费探针或生产数据更新。

SEM、SEO、GEO 都须取入此补丁并独立验收，不能由单服务升级宣称跨服务已保护。
监控的 pending 字段仍只代表尚无终态的 requested，unknown 单列；管理预算 active_calls 的语义是保守占用。

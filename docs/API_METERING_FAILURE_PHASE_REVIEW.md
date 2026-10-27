# 计量失败阶段分类（2026-10-11）

共享异常 `MeteringUnavailable` 保持 RuntimeError 基类、原消息与构造参数兼容，增加
`provider_attempted` 布尔字段，默认 false。准入或 requested 初始提交失败，已知未发送，字段保持 false。
进入供应商调用后，终态写入/提交失败，显式设置 true；供应商可能已扣费，任务结果必须为 unknown。
调用方仅按字段分类，不比较异常消息。ControlDenied 是已知未发送的准入拒绝。
不自动重试、释放占用、估计免费，也不由任务状态反向修改调用台账。

新原生 PostgreSQL 测试使用隔离 schema 的数据库触发器制造真实 INSERT/UPDATE 失败：
初始 INSERT 失败 → 发送零次、台账零行、provider_attempted=false；
HTTP 成功、明确 HTTP 400、网络超时三种供应商结果下，终态 UPDATE 失败 → 发送一次、
provider_attempted=true、已提交台账仍 requested、下一次准入被同一并发占用拒绝。
供应商全部为 MockTransport，触发器只在随机测试 schema，退出即清理。

SEM/SEO/GEO 均须在前两项共享补丁后取入本提交。任务模块独立按此标记更新状态分类并验收；
仅升级共享异常不能证明任务分类已经完成。

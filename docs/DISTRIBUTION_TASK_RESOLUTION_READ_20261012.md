# 发布 unknown 的受控历史核定读取

本地基线：`010f8c0b8f7109d3d37fc607933d8f06a8c36ae8`。这次只补设备读取既有核定结果的接口，不执行核定、不创建任务、不发表。当前实际 b1e28c56 任务仍 unknown，官方列表未完成核验；没有任何真实负证明。

原设备接口 `/api/distribution/handoff/v1/device/resolution` 只接受 action=handoff 并读取 `distribution_handoff_resolutions`，不能用于 publish。顾问 GET tasks 的 resolution 需要当前顾问 JWT，不能交给多号通。多号通 14a 的 `DistributionTransport`/refresh 只提供 handoffResolution；单次 publish runner 仅注入 exchange，所以云端人工核定不自动解除本地旧 unknown 账号拦截。

## 精确协议

`POST /api/distribution/v1/device/task-resolution`，设备 Bearer，禁止 query。请求、响应均 strict/extra forbid，字段 snake/camel 风格沿用独立设备协议：

| 字段 | 类型/意义 |
| --- | --- |
| resolutionVersion | 整数 1，bool/float 不接受 |
| deviceId | 既有设备 Identifier |
| taskId / grantId / publicationGrantId / leaseId | 规范小写 UUID，均为原任务的身份，不签发新值 |
| customerId / projectId / accountId / platform | 原严格 v1 target；本批只接受 SEO，GEO/SEM 不接受 |
| contentVersion / contentDigest | 原任务封存版本与 64 位小写 SHA256 |

请求不能带 action、正文、素材、URL、Token 或顾问身份。响应完整回显上表十二字段，并严格增加：

| 字段 | 类型/意义 |
| --- | --- |
| asOf | 本次完成身份和 SELECT 检查时的 UTC epoch 毫秒 |
| resolution | null 或 `{id:正整数,outcome:'not-published',checkedAt:UTC毫秒,evidence:'advisor-reported'}` |
| publicationVerified | 固定 false |
| executionAuthorized | 固定 false |

resolution.id 来自现有 bigserial，最大为 JS safe integer；它不是 handoff 的 UUID。checkedAt 是历史人工核查时间，必须不晚于 asOf。nullable 结果不表示核定；不得据此解除拦截。示例只含合成数据：`docs/fixtures/distribution-task-resolution-read-v1.json`。

## 服务端与客户范围

真实设备 credential 的 SHA256 验证、当前 active device/binding、原 task 的完整 target/双 grant/lease/source digest、当前 project owner 和原生 SEO adapter 当前 advisor scope 都须通过。保持 device → scope → canonical account 锁顺序，锁后重读 task/binding，并确保最初锁定的 binding/platform/external account 没有变化。project 可 paused/running，revision 改变不妨碍合法历史读取；owner 改变、项目 ended、撤权、范围错误全部拒绝。

首个 task SELECT 后仅允许 module=seo，GEO/SEM 在 scope/account 锁及原生 adapter 授权之前立即 403。工厂也只在 module=seo 时挂该路由，GEO 工厂不装载它。本批没有 GEO 并发或锁序兼容证据；GEO 既有 resolve 的 Tenant→device 与此 reader 的 device→Tenant 授权顺序存在逆序风险，因此保持关闭，不修改其原流程。

仅读现有 `distribution_tasks`、`distribution_task_resolutions`、设备/绑定/项目及当前原生鉴权数据。无 commit/flush、无状态或日志写入、无 source 重载、无网络或 DDL。只有最新存档 outcome=not-published、public_url=null、actor 为原任务顾问，而且 task.failed/revoked=true 时才返回负证明。unknown 且无核定返回 null；较新 published correction、未来核定时间或矛盾状态返回 409。数据库/结构故障安全 503。

旧 task grant 已过期/被撤销属于历史闭合条件，不要求恢复。当前 device/binding/顾问范围撤销则无法获得有效读结果。负证明不恢复旧 grant，不放行旧任务重放。工厂只挂这个真实新 reader，保留 owned get_session override、原 PrivateRoute 的 request limit/no-store/安全错误；manifest 记录三个新源码文件与 fixture SHA。原 core/scheduling/auth/strict-v1 receipt/single-publication gate 不变。

## 多号通后续接线边界

应增加独立 publishResolution transport/validator，不能把 handoffVersion/UUID proof 直接套用。当前轮成功读到完整匹配负证明，asOf 不晚于设备当前时间且年龄 <=5000ms，才能解除该旧 unknown 的 lane 阻挡。checkedAt 可以是历史时间，不用于响应新鲜度。

本地旧 unknown receipt/audit/单次 import/submit claim 均保留。历史 proof 可存作审计，但它不能单独解除 lane；重启后、读取失败、null、409、撤权、时间回退或 proof 变更时继续阻挡。每轮、尤其下一次 dispatch 前重新读；不以 INSERT OR IGNORE 的陈旧记录永久豁免。原任务不能重放，下一篇仍必须有新的中央合法 task、双 grant、lease、原生内容审核和发布节奏，且旧 import claim 不得删。

## 验证范围

原 `3dce56f4` 冻结检查为 **257 passed**：此前门禁/封面/客户读接口 208 项，加 reader 49 项；原证据保留，不改标到新提交。SEO 限范围修复后，仅复核受影响 reader 专项 **51 passed**（原 49，加 GEO 首读拒绝/不进入授权，以及工厂只在 SEO 挂载两项）。这些都是合成数据库 SELECT 哨兵、实际 credential hash 比较、严格 Pydantic、原 PrivateRoute/credential parser AST 及内存 ASGI，没有实际 GEO 并发锁测试。覆盖 unknown 无 proof、不变更任务/绑定/项目、完整旧 tuple、当前撤权/账号切换、锁后复查、latest correction、历史 expired grant、异常安全 503 和工厂/manifest 接线。

它不代表真实 PG 锁/原生 JWT/HTTPS 或多号通 lane 联调已通过，也不代表本次账号官方列表已核查。没有启动服务、执行 DDL、云端/平台请求或改真实 task/STATE。后续由根窗口独立审查、集成并先用当前 unknown 验证 null；真正人工核查完成后才能测试合法负证明与多号通 fresh 恢复。

XML：私有 TEMP `distribution-publish-resolution-read-tests-20261012/publish-resolution-read.xml`，SHA256 `c4de505d941a3cfe5ecd9d86dce817a6c4cd0af9e6fbd421b49b4e4bbda852ae`。

SEO 限范围专项 XML：同目录 `publish-resolution-seo-only.xml`，51 tests/0 failures/0 errors，SHA256 `5cc2e4c33f95b1ddca07b8467a2ae8c3175ff388410b293cfd50a0a8b5ec2b0d`。

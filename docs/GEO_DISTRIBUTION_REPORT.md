# GEO 多号通人工结果回传

此功能默认关闭；只挂在独立 GEO 服务 `/api/v1/geo/distribution/v1`，不依赖 SEO，不挂 SEM，不新增表、迁移、第三方服务器依赖或 env。

## 操作

1. 已获当前客户授权且被分配到当前项目的顾问，或已登录的超管，选择 GEO 客户。在「项目管理」点击一个项目行，在选中项目的「多号通结果回传」打开当前项目回传。顾问仍受原 `advisor_scoped_content_writes_enabled` 与巡检/周期/服务计划门禁限制；未开放时显示只读，不修改服务器配置。
2. 在「分发平台」的「多号通结果回传」选择同一项目、已有公众号人工账号，填写设备显示名称，生成配对码。没有账号时由原有管理员维护流程准备，设备不能自行建账号或改客户。
3. 多号通 0.3.4 选择 GEO，输入一次性配对码；十分钟内消费一次。结果未知不重复领取，吊销并重新配对。配对准备不要求结果开关已打开。绑定的外部账号身份仍标未核验，不能把设备配对当平台登录证明。
4. 文章通过原有规则与客户审核后，在文章分发页的「多号通结果回传」选择当前项目设备，派发固定版本的公众号稿。配对不自动派稿。
5. 操作人在官方平台发布后，在多号通核对稿件、账号、公开链接并明确确认。客户端发回 `HUMAN_PUBLISHED` 后，服务端复用 `_write_publication()`，同事务保存账本和原生记录，提交后才 ACK。
6. 分发页显示送达、人工报告结果、页面核验三种事实。既有十分钟 monitor 批处理恢复 pending 检查；只有当前 URL、版本、正文 fingerprint 与原 monitor 的实际证据均满足才显示页面核验通过。风控、需登录/验证、审核中、失败、未知只记结果，不创建成功 publication，也不关闭原有业务工单。

关闭当前项目只改变该项目二次开关，保留其他项目开关；不删除历史，不 ACK 新结果或重试结果，不停止既有 publication monitor。吊销后凭据、任务与回传即时不可用。授权人失权、项目移动、账号禁用、母稿/渠道稿变化均重新检查。历史非成功观察可在仍合法归属时登记，不改当前审核状态。

## 契约和存储

`TenantModule(module_code='geo').module_settings.distribution_report_v1` 保存带 schema 的开关、配对摘要、设备摘要、固定任务引用和双流账本。按 Tenant → TenantModule 取行锁，刷新 ORM 后保留其他设置命名空间。native 发布在同一事务内；异常整批回滚，无部分 ACK。此 JSON 试点的容量为 5 个活跃设备/未用码、100 个活跃任务、1000 个累计任务、每任务每流 64 个事件、8 MiB 总账本；满后拒收，不删去重历史。

凭据使用既有配对 JSON schema 要求的 **64 字符 base64url opaque 值**，服务端仅保存 SHA-256；使用 GEO module 行内精确 JSONPath 摘要查找与常量时间比较，不扫描 SEO。设计 5.3 的 `dr1...` 是建议定位格式，不能通过既有冻结 schema 的 64 字符校验，因此没有采用。bindings 保留冻结 schema 必填的 `schema:1`。这些是对现有配对协议的兼容，不向已有 JSON 添加未定义键。

有状态设备 POST 使用持久 `X-Distribution-Request-Seq` 与 `X-Distribution-Sent-At`；五分钟时钟窗口，完整原始 body、method、path、序号与时间共同做指纹。同序号仅完全相同可重试；更高传输序号可重送同业务事件并获得原 ACK。业务事件 ID、task+stream sequence 和完整事件摘要共同去重；允许跳号，拒绝未知旧事件。所有成功 URL 必须是原样 `https://mp.weixin.qq.com/s/<short>`；不猜测或删去 query。

人类管理入口只接受已有登录身份，API key 不能签发长期设备授权。顾问路由使用精确四条写规则和两条读规则，保留原有 grant、assignment、总写入开关及提交前复查。设备请求不伪造管理员上下文，不使用人的 JWT、平台凭据或管理员密钥；按保存的签发人 ID 重查现行角色、grant 和项目分配。浏览器 Origin/Cookie/Sec-Fetch 请求拒绝，配对/设备回包与错误均 no-store。代码不记录请求原文、配对码、credential、hash 或任意异常文本。

## 本期边界

首期只接现有证据最充分的公众号人工交接。仅接受无图片/媒体的已审核稿件；检测到素材或封面表示时明确拒绝，不能省略图片继续派发。完整受控素材端点和第二平台不在此次文本稿试点内。本文不声称已用真实账号完成发布验收。

后端测试：`python ops/run_geo_checks.py --postgres`（仅专有 loopback `geo_ci` 空库）。新增原生 Postgres 测试实际竞争单次 claim、竞争回执、在 native 写后中断并验证全事务回滚、跨项目拒绝、无关 JSON 命名空间保留和 monitor pending。无本地 PostgreSQL 时的 skip 不是通过证据，合并必须看 GEO CI 的 PostgreSQL 结果。

前端：`node --test tests/geo*.test.mjs`（frontend），`npm run build`（frontend/geo-frontend）。启用须等后端、客户端相同契约审核及 CI 通过；遇生产 schema/权限缺口另列方案并停止，不在应用内自动补表或改 env。

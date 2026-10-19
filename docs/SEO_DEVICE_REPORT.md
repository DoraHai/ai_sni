# SEO 多号通人工确认结果回传（一期）

本功能默认关闭，只接微信公众号 `wechat-article` → 既有 `wechat_browser` 人工连接。选择依据：客户端已有固定稿件交接、人工确认、公开短链接识别及相应拒绝测试；其他平台缺少同等绑定/链接证据。本期不调用官方发稿 API，不自动点击发布，不读取平台凭据。

## 操作

1. 顾问登录后选择已授权客户和已分配的网站；超管也可操作。在「国内内容分发中心 → 多号通结果回传」选择现有、已绑定该网站的公众号连接。
2. 填写执行电脑备注，生成一次性配对码。码有效 10 分钟，显示后不持久保存在浏览器；关闭页面或切换客户/网站/身份会清除。领取不确定时不要自动重领，由顾问/超管吊销后重新配对。
3. 执行电脑使用支持模块前缀的多号通新版，选择 SEO 模块，输入配对码。旧固定 `/api/distribution/v1` 客户端不兼容，不能启用。
4. 在相同客户与网站开启回传。客户模块开关与网站开关必须同时为真；开启某个网站不隐式开启其他网站，SEO 不影响 GEO。关闭客户开关会停止该客户所有网站接收和派发，历史及客户端待传结果保留。重新开启客户时只激活当前网站，其他网站须分别明确开启。
5. 按原流程审核主稿、客户确认/顾问代确认、准备公众号发布任务；选择任务及执行电脑派发。请求绑定精确版本和内容摘要，版本变化后必须重新核对。
6. 人在官方平台完成发布，在多号通核对固定稿件后点击「确认链接并回传」。成功仅接受 `https://mp.weixin.qq.com/s/<short>`；风险、验证码、需登录、失败、审核中、未知等结果分别回报，不携成功 URL。
7. 卡片分别显示回执送达、人工结果、页面核验。人工报告已发布不等于核验通过；正文完整匹配和原有截图证据均满足时才显示通过，链接发现沿用原有流程。核验缺口保持待处理/暂不可用。

顾问仍受当前 `advisor_tenant_grants`、网站 assignment、角色编辑权限和既有顾问总写门禁约束。这里不提供开启既有服务器开关的途径，不增加新 env。普通客户账号与 API Key 不属于设备管理身份；设备凭据不拥有管理权限。

## 路由与数据边界

只在 `app.seo_main` 挂 `/api/v1/seo/distribution/v1`，不在共享应用或 GEO 挂载。管理路由为 GET/PUT settings、POST device-pairings、POST devices/{deviceId}/revoke、POST tasks、GET tasks/{taskId}；显式 query 为 tenant_id、site_id。设备端保留 claim、bindings、exchange、task-resolution，扩展 observations 与只读 verification。

配对码为 24 随机字节、32 字符 base64url，设备令牌按冻结客户端 schema 为 48 随机字节、64 字符 base64url。数据库只存完整值 SHA-256，仅在 SEO 模块设备安全字段中按精确哈希定位，锁定后重新比较哈希和固定绑定。令牌不复用用户 JWT/API Key/平台凭据，过期或吊销拒绝。浏览器 Origin/Cookie/Sec-Fetch 请求不能调用设备接口，设备响应 no-store。

有状态设备 POST 必须带 X-Distribution-Request-Seq 与 X-Distribution-Sent-At；五分钟时钟窗、严格递增高水位，同序号只在 method/path/body/time 完全相同且当前授权仍有效时重取原 ACK。事件独立账本按流保存 ID+完整摘要、sequence、原 ACK；允许跳号，未知低序号和冲突拒收。整批 native 变更、业务审计、账本与核验意图同事务提交后才 ACK。

安全账本使用现有 tenant_modules.module_settings.distribution_report_v1。写前按既有网站/顾问锁顺序获取网站及模块锁，刷新模块对象，深复制本命名空间；顾问 commit guard 只用 Core 列重新检查锁和门禁，不能用 ORM populate_existing 覆盖未提交 JSON。其他配额命名空间保留。

上限为每客户模块 5 个活跃设备、5 个未用码、100 个活跃任务、1000 个累计任务、每任务每流 64 事件、整个命名空间 8 MiB；达到上限拒收，不删除幂等历史。配对按 ASGI 来源、码摘要及较高全局兜底限流；配对与已认证设备使用独立的有界限流表，随机伪造令牌不能占用设备额度。429 返回 Retry-After。

超管管理写入也在事务内重新锁定并核对当前账号/角色；顾问复用既有提交前 guard。旧人工 complete 与设备同时回填同一记录只产生一次原生变化；原生变更 flush 后若本事务失败，发布事实与账本一并回滚且无 ACK。

## 核验与恢复

成功回执只调用旧人工 complete 共用的无 commit 事务核心，保留主稿审核、固定版本、有效确认、平台专属稿审核、原生 URL 去重及离线专用记录隔离。旧 HTTP complete 的权限、错误处理、提交和截图排队仍由原 handler 处理；助手 JSON 与离线导入入口不变。

核验意图与回执同事务落库。提交后的后台任务和既有 SEO scheduler 均可恢复，网络抓取在数据库锁释放后执行；仅重做检查，不重发稿件。正文核验复用安全抓取和 `observe_answer()` 的完整正文匹配、最短长度、相同 URL/主机规则；核验前后复查版本/URL/授权。原截图和外链检查继续运行，不据 ACK 关闭服务任务。

## 一期限制与部署

不新增表、列、索引、第三方服务器依赖或 env，不执行迁移。必须已有 0105 及后续确认 schema；缺 schema/运行权限时拒收，不自动修复。如果运行角色不足或部署需手工配置，应单列方案并停下，不扩 sem_runtime。

素材受控传输尚未实现，带图片、媒体或内联样式的任务明确拒派；不能漏图继续发。账号外部身份显示待核对，不能把连接映射 ID 当作平台身份验证。未知状态不签发自动调查结论，task-resolution 返回 resolution:null。

测试向量在 tests/fixtures/distribution_report_vectors.json，由 Node JSON.stringify 产生；包含中文、emoji、换行、控制字符、组合字符和素材顺序。新增 PostgreSQL 测试必须使用独立 loopback seo_workflow_test 数据库；不设置测试 DSN会失败，不能以 skip 通过。SEO baseline workflow 既有本地 PG 服务执行这些测试并检查零 skip。

审核通过且 CI 全绿后，按共享 merge.lock 串行、普通 merge commit 上线，观察既有 workflow，并只读 GET 检查健康。本文不替代 Codex/Cursor 审核或部署验收记录。

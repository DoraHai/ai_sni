# 顾问每日自动检测后端

依赖 PR1 的 `0075_geo_autopatrol` schema，默认不启用任何客户。本 PR 不执行迁移、不增加 env 开关、不放宽 sem_runtime，不包含部署修改。

顾问使用 self-service 小接口，仅提交 tenant_id/enabled/expected_revision。只覆盖开启人已负责的项目，最多20个有效问题；持久保存用户、grant代次和范围摘要，不保存 JWT。超管只能查看、强制关闭加锁和解锁，不能代开。关闭不退回旧定时；原 PUT settings 对自助客户拒绝写入。

manual_daily_limit 存数据库、默认10、范围0–100。顾问共用客户日额度，超管修改有独立版本和审计。普通 manual 与 contract_retest 是检测轮次，reservation_only 是其他操作的原有预约账，不占轮次额度；自动不扣手动。失败无有效结果退款，部分成功计次，删除普通历史保留额度凭据；auto_day 记录禁止删除/cleanup。

北京时间08:05–11:05按客户ID分散，客户锁内占唯一auto_day。安排与执行分离；两个固定全局advisory执行槽，独立服务每2秒查队列，原应用调度器每分钟查队列。只领取当天未启动pending；旧日pending取消，已running的中断轮次标失败不重放。run锁存续期间恢复器不能回收活任务，last_progress_at记录进度。

每次真实可见度回答、判读和重试之前单独短事务原子计数，代码常量36000/北京请求日；失败也计数，预算不可用时停止外呼。自动输出上限4096 token；六家专用平台凭证，缺项跳过，不使用共享模型人设；DeepSeek托管身份需确认模型，元宝展示为混元API。hy4-采用与 #793 相同的窄身份前缀修复，不追认历史。

任务安排、外呼前后和落库前复核设置revision、用户角色、grant、项目业务绑定及冻结问题哈希；撤权后返回内容丢弃。401/403在同轮只尝试一次，后续该平台格跳过。下次预计为北京时间，不保证当天一定成功。

测试使用合成账号、虚拟供应商和自有临时SQLite/CI loopback PostgreSQL随机schema。数据库测试覆盖两个生产者同日竞争、跨日预算并发、两个执行槽、重启不重放；不使用单进程mock证明数据库互斥。现场平台可用性、真实数据和运行角色权限均未核验，部署前需单独审核；权限不足不得上线。

保留手动/精确复测的客户级日外层保护（代码默认24）：统一由 manual_quota/manual_condition 统计客户共享手动轮次，排除自动、self_service、schedule 和其他操作预约空行；触发时返回 TENANT_MANUAL_SAFETY_LIMIT，tenant_run_limit 只表示这一手动外层保护。即使手动外层已满，自助队列仍可安排当日唯一自动轮次，不再用手动额度拦截自动。它与36000次平台请求闸不同。未迁移客户的 legacy 调度保持既有日上限。单格探测/搜索等 reservation_only 操作保留既有顾问级独立10次预约规则，不占本次客户轮次额度。

调度及顾问状态将 HTTP detail.code 映射为安全 blocked_reason：无有效问题为 no_prompts，项目分配/客户授权变化为 authorization_changed，GEO 不可用为 geo_unavailable，未知错误为 blocked（界面通用阻塞文案），不回显原始错误详情。

自动路径的引擎查询只加载 id/tenant_id/key/enabled/sort_order，并禁止隐式读取其余字段；不读取旧租户加密凭证列或租户 AI 设置。平台凭证只由既有平台解析器提供。

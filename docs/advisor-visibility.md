# 顾问手动检测一次

仅新增顾问入口：`POST /api/v1/geo/visibility-patrol/runs`，处理函数
`create_visibility_patrol_run`。前端 `GeoVisibilityView.startCollect` 使用同一接口。
请求 query 和 JSON 都指定当前客户 `tenant_id`；顾问 JSON 只接受这一项。
这是一次手动运行，不会开启定时巡检，也不会更改引擎或巡检设置。

必须打开原有 `ADVISOR_SCOPED_CONTENT_WRITES_ENABLED` 开关；顾问须已获客户授权、
已选择当前客户、拥有 GEO 编辑权限与权益，并有分配给自己的 active 项目。
仅使用这些项目下最多 20 个 active 问题；没有问题就拒绝，后台不回退到全客户问题。
问题清单在入队时保存，提交前重验授权、项目分配和问题范围。
客户启用巡检、active 周期或服务计划时，仍由 `check_manual_execution_scope` 拒绝。

新增配置 `ADVISOR_VISIBILITY_MAX_RUNS_PER_DAY`，默认 **1**，范围 1–24。
按每顾问、每客户、上海自然日计启动次数；失败也计次，重启不清零。
使用已有运行记录的 `created_by / tenant_id / created_at`，没有新增表或迁移。
保留客户原有 `GEO_PATROL_MAX_RUNS_PER_DAY`（默认 24）、精确复测预约限制、
`GEO_PATROL_MAX_CELLS_PER_RUN`（默认 200）及后台每格 GEO 权益检查。
每次供应商调用继续经过 `chat_json -> metered_request -> api_controls.admit`。
API 的额度、预算、计量和限流检查没有旁路。

创建运行时持有客户行锁，并检查所有创建者的 pending/running 记录；
已有运行就返回 409。现有新调度器已经使用此锁与检查；旧调度器和精确复测入口
也补齐同客户互斥，避免从其它入口与顾问检测重叠。不会自动结束已有检测来抢位置。

顾问不能提交模型、引擎、问题上限、同步/异步、批量、频率等开关。
前端显示“手动检测一次”，保留只读结果与证据；隐藏或禁用其它写入和配置按钮。
拒绝时显示后端原因，例如次数用完、已有检测、没有项目分配。
单独 probe、probe-batch、内容生成、AI 审核、提交审核、审核通过、正式发布、
外发、删除和权限变更没有新增授权。

## 一次大概花多少

顾问最多 20 个问题，乘以客户已启用的引擎数（不含 other）；
仍受单次格数上限约束。仓库默认有 8 个非 other 引擎，若全部开启且问题足够，
就是 20 × 8 = **160 格**。实际数量取决于客户问题和启用引擎。

每个有可用凭证的格子正常调用两次：一次采样回答，一次独立判读，使用同一已解析模型。
采样遇连接或读取超时最多再试一次，所以通常 320 次请求，含超时重试最多 480 次请求
（160 格的例子）；缺凭证、权益或计量拒绝时会少于此数。
这不是允许批量接口；是现有“一次检测”内部的采样规模。

模型由平台的每引擎配置决定，缺配置时还受原有 real_only / simulation / hybrid 定位限制。
代码默认包括 gpt-4o-mini、deepseek-chat、qwen-max、hunyuan-turbos-latest、ernie-5.1、
kimi-k2.6、sonar、doubao-seed-2-0-pro-260215；DeepSeek 也可能用百炼模型。
实际运行模型可在检测明细查看。这里没有读取线上配置或密钥。

`chat_json` 没有设置固定 max_tokens；输入含问题，判读输入还含完整回答，
输出长度由模型响应决定。仓库不足以推算每次输入/输出 token 或人民币金额，
也不知道平台实际费率、缓存命中和重试账单，不能给出可靠的“每次几元”。
应以已有 API 计量记录为准，不能把请求次数当成金额或硬性 token 上限。

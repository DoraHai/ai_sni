# 顾问工作流 v2 发布与回退清单

本文件是可审阅的发布方案，不执行发布。GitHub 暂停期间继续本地开发；SEM 不启动 AI 接管，负责人交接不开发，官网写入与自动发布保持预留。

## 固定候选与本地证据

四个独立单元为组合工作台、SEO、GEO、超管。各自提交必须清洁，SEO/GEO 共享核心及三份 SQL 的六项 Git blob 必须一致。工作台构建清单对应组合工作台提交，校验全部产物、62 个本地输入、两个宿主会话源文件及两个锁文件。不能拿旧候选的 HTTP 样例验收新候选。

`scripts/verify_automation_candidate.mjs` 为只读本地预检，不连接服务器、不执行 SQL，不把本地通过转换为生产许可：

```powershell
node customer-workbench/scripts/verify_automation_candidate.mjs `
  --advisor 'D:/SNIPERS国内版/ai_sni-worktrees/enterprise-onsite-async-ui-20261011' `
  --seo 'D:/SNIPERS国内版/ai_sni-worktrees/seo-ai-planning-20261010' `
  --geo 'D:/SNIPERS国内版/ai_sni-worktrees/geo-onsite-ai-jobs-20261011' `
  --platform 'D:/SNIPERS国内版/ai_sni-worktrees/platform-balance-coverage-ui-20261010' `
  --seo-http "$env:TEMP/seo-automation-v2-http-samples.json" `
  --geo-http "$env:TEMP/geo-automation-v2-http-sample.json" `
  --linux "$env:TEMP/linux-automation-validation-20261011.json" `
  --report "$env:TEMP/automation-release-preflight-20261011.json"
```

预检同时验证样例提交、no-store、原生 Linux 成功且无跳过，以及两个 Linux 调度源文件、四个模块测试文件和工作台补充进程测试文件与候选一致（模块源码按 Git LF/Windows CRLF 正规化）。缺少任一冻结构建输入、文件被修改或补充测试源码不一致都会拒绝。它不代替真实登录链测试、角色权限或现场验收。`production_release_approved` 固定为 false，尚未完成的生产门槛一直列出。

## 数据库独立审核

审核 `automation_projects_schema.sql`、`automation_projects_v2_schema.sql`、`automation_projects_permissions.sql` 的准确 hash、目标数据库/schema、现有运行角色及执行顺序。基础四表、外键、审计不可变函数/触发器及索引先安装，v2 的 `ended_at` / `safe_changes` 随后安装，权限以既有实名运行角色授予。

- 运行身份不得拥有表或 DDL 权限。项目/运行只准必要 SELECT/INSERT/UPDATE，事件和命令只准 SELECT/INSERT；DELETE/TRUNCATE 禁止。
- 检查完整结构、类型、外键、不可变触发器和 ACL；半安装、同名异构、权限不足须停止。三个脚本不是可盲目重复执行的迁移器。
- 隔离 PostgreSQL 验证不代替生产人工审核。历史批准的费用台账建表不涵盖本次项目控制/v2/权限结构。
- 本批不删除客户、账号、调用台账或审计记录，不使用破坏性 down migration 回退。

## 发布顺序与现场验收

1. 记录每个线上单元的实际提交、旧构建 hash、配置和兼容回退版本。线上首版不能按尚未部署的 v2 能力宣传；新旧菜单和原客户功能分别检查。
2. 暂停新项目开启及本轮相关自动请求，核对在途任务、已准入请求与未知费用。默认一次运行，不能批量开启所有客户。
3. 完成人工审核后，使用仓库既有脚本按独立单元发布兼容前端和 SEO/GEO 后端。GEO 使用既有 `scripts/deploy_geo_api.sh`；不得手改发布产物。数据库结构作为独立步骤启用，发布脚本成功不等于结构审核完成。
4. 同时核对部署目录与冻结源码提交、完整产物 hash、宿主会话源和真实鉴权路径。后端 health 200 仅说明有限接口可读；必须单独检查实际 executor/queue、当前进程及所有部署实例。
5. 使用限定测试客户/网站/项目和实名顾问验证：保存不会开启；明确开启；并发重复开启不重复调用；暂停阻止后续请求；结束本轮与结束项目不同；撤权和跨客户拒绝；迟到响应记账但不得采用。
6. 输出核对：已选操作/目标与事实来源一致，规则步骤与 AI 草稿区分，任务成果可在原模块核对；未知费用不是零，调用次数上限不是金额预算。没有完整公开事实或未通过质量门禁时转人工。
7. 用已计量、受限的小范围模型任务实测并独立评分；每案至少 85/100 且无严重违规。业务门槛、供应商可用性和效果数据分别验收，不能用离线回放代替现场模型可用性。
8. 全流程验收包含顾问审核、人工官网实施与真实复查。本轮产出后等待人工结束本轮；冻结/完成的首次草稿或来源变化须重新明确配置，不承诺月月自动出合格成果。

## 兼容回退与演练

出现越权、重复调用、停控无效或不可核实费用时，先停止新开启并暂停项目，关闭后续周期，保留请求准入、供应商回执与审计记录。已发出的 HTTP 请求不能撤回，必须收口并记录结果；不能以“页面已暂停”认定没有费用。

回退应用前逐项核对：

- 未派发、已准入、供应商在途及已返回未采用各自数量与负责人处置；未知调用不得自动重发。
- 旧版本是否理解 v2 接管归属、逐请求账本、`end_project` 和未知计量。**不能回退到忽略接管归属、让旧调度器恢复执行的版本。** 没有兼容旧版本时保留新版本停控状态，修复后向前发布。
- 队列消费者是否仍能识别已有作业；不能切回无消费者的旧后端遗留任务。回退时不删除作业、费用占用或历史日志。
- 既有金额核实记录是否仍被共享准入口径识别；不得回退到忽略 `verified_amount` 的旧准入实现。本文不重新开启或关闭资金保护开关。
- 前端可独立回退到兼容界面；若旧界面没有完整停控语义，先由新版本正确停控，不能靠移除按钮停止任务。

本地回退演练验证构建/版本不一致拒绝、过期 HTTP 证据拒绝、停止后的迟到回执及真实 Linux owner 退出后的锁接管。生产服务管理器重启、实际队列排空、数据库备份恢复和兼容旧发布切换仍须在现场演练，不计为已完成。

## Linux 本地验证范围

`scripts/check_linux_automation.py` 在临时本机 QEMU/Alpine 真 Linux 内核中导入实际 GEO 调度代码，执行现有调度/观察测试和真实进程退出测试。测试拒绝 Python 网络连接，数据库为固定无效地址，不执行供应商或业务回调。保留内核、Python/依赖版本、测试数及源文件 hash。

本机来宾依赖版本与生产 requirements 不完全一致，所以证据只覆盖真实 Linux flock、实际函数的互斥/启动/待命接管逻辑及隔离回调观察，不宣称生产环境一致或全体 worker 健康。标准 Linux 源码检出和完整依赖环境也可重跑该脚本。

官方工具说明：[QEMU 下载与 Windows 构建来源](https://www.qemu.org/download/)、[Alpine QEMU 使用说明](https://wiki.alpinelinux.org/wiki/QEMU)。临时镜像与工具先核对上游校验和；测试结束关闭虚拟机和本机快照服务。

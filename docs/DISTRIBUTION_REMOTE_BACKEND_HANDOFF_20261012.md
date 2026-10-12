# 公司电脑多号通远程控制：后端交接

本轮完成中央后端的有界远程控制接口，供公司专用 Windows 电脑上的多号通主动领取指令，顾问在网页远程操作指定账号窗口。默认开关关闭，正式发布仍关闭。尚未完成真实公司电脑 GUI、微信登录和标准顾问网页的整链验收，不能据此宣布可生产发布。

## 冻结范围与装载

- 基线：`257895ed37e098d7697fa1aa28e13eb87f4d2986`。
- 可运行代码提交：`7a03c83272222995a5b5a7907000dfd6676f2df5`；tree：`aff07a2aeb463f3ad52d10ac6fa3f1a6da61b2c1`。
- 顺序取合同与实现：`d8f7610a8010c43a2721e3c780fba99e2a5a8de4` → `f1f0e0bd95fb4b6e1b838e4103b57e6dd3d2167c` → `7281f324f6e1109cb2b41fa08eac170e34a0ecd9` → `7a03c83272222995a5b5a7907000dfd6676f2df5`。后续证据提交仅docs，不改变该运行版本。
- 新增 `app/distribution_remote_contract.py`、`app/distribution_remote.py`、`app/api/distribution_remote.py`；原 `app/api/distribution.py` 只追加remote router挂载。
- `scripts/distribution_remote_schema.sql` 只增加remote sessions/commands两张可选元数据表；没有生产DDL。
- 测试辅助文件为 `scripts/distribution_remote_test_service.py`、`tests/test_distribution_remote_https.py`。合同JSON在 `docs/fixtures/distribution-remote-control-v1.json`。
- `main/auth/models`、原生SEO/GEO审批和source adapter、SEM均未修改。旧验收树、旧PG和根pilot端口未操作。

应用只挂原distribution router一次，即进入remote router的lifespan；也可以独立只挂remote router，不能两者重复挂载，也不能在factory另调用broker.start。只有环境变量 `DISTRIBUTION_REMOTE_CONTROL_ENABLED=true` 才启用。单实例、单worker，专用PG advisory owner连接与普通API池分开；第二实例不能抢占第一实例。

精确端点、字段、7个PNG响应头、三字段顾问task请求/五字段设备task响应、输入与ACK枚举见 [合同](DISTRIBUTION_REMOTE_CONTROL_V1.md)。公司电脑沿用已有device Bearer/绑定/授权；一次性新设备配对后续开发。供应商直发、平台排版后置。

## 已验证的边界

| 检查 | 本轮实际结果 | 范围 |
| --- | --- | --- |
| 当前实名顾问与客户范围 | 通过 | 真实原生JWT、assigned advisor；客户、错误顾问、跨客户/项目、撤角色/撤指派拒绝 |
| 当前设备与账号范围 | 通过 | 现有device Bearer，错设备、失活绑定拒绝；device/账号有效会话排他 |
| 内容及任务介入 | 4项通过 | 原生SEO创建、内部独立审核、顾问版本确认、非AI渠道适配、渠道审核、actual source、中央task/grant/lease；错scope、新pending渠道版本、租约过期、暂停均拒绝介入 |
| 登录准备与发布隔离 | 后端约束通过 | 项目paused可登录准备；task介入要求running及原控制版本；不创建/恢复publication grant，publish动作拒绝 |
| PNG及输入 | 通过 | 尺寸/大小/有界解压、迟到/未来/错视口拒绝；7响应头由当前session派生；仅有限鼠标/键/文本；无输入错误回显 |
| 命令重放与视口变化 | 通过 | UUID单次、首次poll后不重发，ACK精确元组；变视口撤销旧输入、旧ACK拒绝 |
| 全局容量与失败清理 | 通过 | 两个真实原生scope、10并发创建，仅8成功；真实PG审计和commit故障后槽位释放 |
| broker归属与重启 | 6新增项通过 | 第二进程不抢owner；owner锁丢失503；queued/delivered重启后分别canceled/unknown，无输入及PNG恢复；默认关闭实例不影响已启用实例 |
| 存储与最终运行来源 | 通过 | PG只含动作元数据；最终actual HTTPS health的6个文件hash与冻结代码一致，最终PG无active remote session |

共29个不同用例，33次通过观察：首批19项、原生任务4项、runtime专项9项（含3项受影响重验）、冻结运行版本1项重验。没有把重复用例加算为不同覆盖。没有重跑前几轮与本接口无关的大套件。

测试使用自己的loopback PG `55537`、HTTPS `55871`，默认关闭实例另用 `55872`，私有根目录为 `%TEMP%/distribution-remote-broker-tests-20261012`。真实原生SEO装载固定 `b4d8387123355348f79e26ea2838585c5106a4b9`，实际执行0105 migration；测试数据全部合成。HTTPS验证新自签CA，未全局忽略TLS。输入和PNG消费者是合成executor，没有调用微信平台、付费AI或真实发布接口。

早期seed时的 `native-manifest.json` 记录初始合同提交d8；它不能代替最后运行证据。最终重启服务运行7a03，`runtime-manifest.json`、`final-runtime-health.json`记录实际冻结HEAD及文件hash。首批19/4用例在开发过程中完成；关闭命令状态与身份绑定受影响的3项另在runtime专项复核，最终又核验实际7a03运行下的身份/范围/PNG头。文档提交不需要重启服务。

## 后续必须实际联调

总控还需在独立pilot连接真实多号通GUI和标准顾问页面，验证账号BrowserWindow范围、鼠标坐标/键输入、微信登录/验证码、断网及unknown提示、关闭/撤权后的执行端停止。执行端必须网络级拦截正式上传/发布；中央不会通过截图推断按钮用途，后端接口测试不能替代这一安全验收。task-intervention需继续用服务端当前完整tuple核验，不能通过登录会话扩权。

本轮未实测GEO原生remote task全链、活跃平台上传中断、真实微信发布。多worker刻意不支持。没有推进云执行服务器、供应商发布通路、一次性新配对或SEM接管。

## 证据

非秘密JSON索引为 [DISTRIBUTION_REMOTE_BACKEND_TEST_EVIDENCE_20261012.json](DISTRIBUTION_REMOTE_BACKEND_TEST_EVIDENCE_20261012.json)，包含XML计数、文件SHA、最终运行文件SHA、独立PG状态检查和明确未验证项。

原始XML、原生migration记录、最终运行/PG元数据保留在上述独立TEMP根；密码、JWT密钥、device credential、control nonce、输入值和截图不进入Git或本报告。XML只含用例与合成参数。正式发布始终false，没有生产数据或生产环境变更。

收尾已停止本窗口自有HTTPS和PG，55537/55871/55872均无监听，私有数据和证据保留；没有停止其他旧验收环境或总控pilot。

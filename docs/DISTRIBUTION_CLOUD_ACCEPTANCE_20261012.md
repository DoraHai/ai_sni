# 公司执行电脑分发验收 · 2026-10-12

本轮已部署独立 Linux API／数据库验收环境，完成实际网页配对、公司 Windows 执行端绑定、原生 SEO 稿件准备、单条预检领取及待人工回执。**完整真实发布尚未验收**。用户决定稍后扫码；没有核验真实公众号身份，没有导入编辑器、上传封面、提交发表或获取公开文章链接。SEM 未部署或启用 AI 接管。

## 可复核的部署与仓库版本

| 单元 | 验收源提交 | GitHub 独立分支快照 | 完整源树 |
| --- | --- | --- | --- |
| 中央工作台／API | `25ce3f99668f16986f1e2c014e2307811f10df1f` | `6478c2816518c8822cdf9b1e5982ae7b145b81a0` | `a34a37a6c71e270a0180695f9df8128b5c139fd3` |
| 原生 SEO | `b4d8387123355348f79e26ea2838585c5106a4b9` | `6a851241ad6df5cda9a14c91419a4338bae06fef` | `625c431d432ba23f6c7f0f28de18bb16bf417b5e` |
| 原生 GEO | `46dacbd805afc00f37eba344306fde004039efed` | `8737194fdf6f0f2517fc831794a320d7a40e2fc0` | `259699522c8694171738972b23a32ad81a0ab0ed` |

GitHub 插件同步采用完整 UTF-8／mode 树与期望分支头校验，三个快照均与本地源树严格一致。未合并到 main；旧 SSH 身份仍不可用，改用已连接插件同步。GEO 历史共享文件只归档在独立 GEO 分支。

服务器目录 `/opt/gsnipers-distribution-acceptance`；数据库 `distribution_acceptance_seo`／`distribution_acceptance_geo`，独立 schema `acceptance_seo`／`acceptance_geo`。API 只监听 loopback HTTPS 55861／55862，通过本次独立 SSH 转发验收，不改变生产 Nginx 或生产数据库。三个自有服务未启用开机自动启动，未启动全域分发 worker。实际客户快照仅私有传输，不进入 Git。

## 实际验收结果

| 环节 | 结果与边界 |
| --- | --- |
| 网页首次配对 | 原生命名账号登录；一次创建短码；真实 Electron 领取一次，服务器确认 claimed／设备 active。长期凭据只保存在执行端，外部 SID 权限规则为 0。 |
| 绑定与登录介入 | 初始 discovery 空；原生配置唯一 SEO15／站点6 绑定后 GUI 重读并选择。真实顾问 API 创建登录会话、读取官方二维码帧均 200。账号仍是明确标记的未核验占位值；未获得真实 `gh_` 身份。到期关闭会话，无静默续期。 |
| 网页身份与输入 | pagehide 清码、缓存恢复重新核验；慢网真实 GET 期间的名称／TTL 输入保留，离开后清空。相关前端 9 项回归通过，另有实际云浏览器验证，无响应模拟。 |
| 权限拦截 | 8 项实际云检查：客户不能配对／控制项目、外部客户不能读测试 scope／source、旧长期凭据创建口拒绝、Authorization／Origin／Sec-Fetch 的网页 claim 拒绝。两模块的真实目录只开放本单元。 |
| 原生 SEO 稿件 | 28 次实际 API 调用。派生母稿61 v2 ready、公众号稿2 revision1 approved，精确版本确认后 source-ready／eligible。审批是命名测试账号及 advisor_proxy，不等于真人内容批准。原母稿60／百家号稿1的正文、版本、状态保留。 |
| 单条任务与回执 | 原生顾问授权一条 preflight，云任务 `3228b482-ebde-434e-9e6e-d353ae8609ca`。PC 实际领取并执行一次，页面未核验时停止；没有平台写操作或 publication grant。经同任务结果桥接，中央最终为 seq4 `HUMAN_REQUIRED`／`awaiting-human`，项目暂停 revision2。 |
| 真实发布 | 未验收。编辑器导入、标题／排版／封面、提交发表、公开链接核验与原生发布回写均没有本轮成功证据。当前正式发布入口仍关闭。 |

## 已发现并处理的问题

1. GEO 的隔离目录入口与原生模块版本不兼容：修正验收入口后，两端实际 HTTPS／命名登录／模块目录复验通过；不修改共享原生鉴权。
2. 配对列表异步重绘擦除正在输入的字段：共享面板改为内存草稿、身份变化清空；本机延迟 DOM 回归及真实云延迟请求验证通过。
3. 隔离 SEO 超管目录显示了 SEM：独立入口保留真实 SEO 权限结果，仅将其他未服务模块标为不可用，两端实际严格 own-module 检查通过。
4. 初次预检把 `pending=0` 误判为最终回执确认：原 seq3 `PAGE_UNVERIFIED` 属于 localOnly，服务器只收到 seq2 DISPATCHED。原记录保留；同 task／lease／version／digest 追加新 seq4 `HUMAN_REQUIRED`，获得完整中央 ack，恢复执行次数为 0。未扩大 strict-v1 白名单，未延长 grant，未重发任务或伪造成功。

执行端修复已冻结在独立多号通提交 `710a1d7de90629a1b8ba2808ff171a0b57b98986`，工作区干净，静态复核未发现恢复闭环阻断。完整六字段 ack 在真实 exchange 校验后同事务持久化；历史总数与尚未确认结果分开；重启从同范围／版本／摘要／租约的持久回执恢复，不重新执行。typecheck 与四个文件中的 75 项相关测试通过；普通已确认记录和保留原 localOnly 的桥接记录，两种离线恢复入口均运行验证为本轮执行0／HTTP0。测试库中新加入 SQL 防修改触发器；实际旧库转送时采用仅追加策略，不能倒推旧历史已有这些触发器。详见多号通 `docs/ACTUAL_CLOUD_WINDOWS_ACCEPTANCE_20261012.md`。

## 后续扫码验收

用户方便后重新创建短期官方登录会话并扫码；读取稳定公众号身份，撤销占位绑定并绑定真实账号。随后用已确认测试版本验证导入、排版、封面／必填项、受控提交、结果未知处理、公开链接核验及原生回写。每一步通过后才标记对应能力，不从配对、素材交接或点击提交推断发布成功。

## 私有证据索引

主证据根：`C:/Users/Administrator/AppData/Local/Temp/distribution-cloud-pilot-20261012`。其中 `cloud-health-25ce3f99.json`、`cloud-admin-pairing-evidence.json`、`cloud-pairing-draft-browser-evidence.json`、`cloud-authorization-guards.json`、`cloud-native-module-catalog.json`、`cloud-single-preflight-before-outbox-race-fix.json`、`cloud-single-preflight-paused.json` 均为状态证据。密码、短码私密文件、设备密钥、Cookie、正文和控制 nonce 不纳入本报告或仓库。

独立后端配对 22 项原生 JWT／PostgreSQL／HTTPS 测试见 `DISTRIBUTION_DEVICE_PAIRING_HANDOFF_20261012.md`。多号通早期 42 项单元／GUI 供应商模拟测试不能替代本轮实际云及真实发布验收；9 项前端、8 项云权限检查、28 次原生 API 调用也不合并表述为完整发布通过。

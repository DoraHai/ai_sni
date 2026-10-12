# 分发交接与恢复：最终本地验收（2026-10-12）

授权范围内的隔离双方联测通过，中央候选与 MHT 候选已冻结。真实平台发文尚未验收，生产未上线；所有 publicationVerified/automaticSubmit 仍为 false。

## 冻结版本

- 中央验收代码：`c4091c8c245ee9524aa738627aa1a82b97ee7c3d`；最后运行规则变更为 `e1d2983441b066c78eea7ade3a5c93f534710248`。后续变更只加入本地联测和证据。
- MHT 最终：`bd8fcc50f2ead8b8cbf07ba6512b40b121e5334b`。使用其 `distribution-strict-resolution-build-20261012.json`；8 个产物、3 个夹具共 11 项全部匹配。独立私有 TEMP 快照导入真实 CapabilityClient、DistributionAgent、HttpsDistributionTransport、HumanHandoffExecutor，未读取变化中的共享 out 运行。
- 历史兼容恢复：首次等待用私有 `834a883276b499bff2cd649abfa5ba63db648fd7` 快照真实产生旧不兼容 outbox，再由最终快照打开同一 SQLite。不是手工伪造合法回执。
- 原生 SEO：`139cc7f57650afb1e83930149b6fac33cb9f861a`；原生 GEO：`ba713f06da330362cd0539531e4edd3216a09d78`，均只读。

逐文件原始字节 SHA、Git blob SHA、最后来源提交、双方产物与夹具 SHA、真实任务/租约和审计记录见 [最终机器证据](DISTRIBUTION_FINAL_LOCAL_ACCEPTANCE_EVIDENCE_20261012.json)。中央 assembled 清单共 21 项，覆盖独立接口、恢复模块、候选 SQL 与三份共享协议夹具。

## 本次针对性结果

`4 passed, 37 deselected`，约 13.83 秒。两项恢复链和两项设备只读授权检查分别如下；与历史计数存在重叠，不能相加为总测试数。

| 场景 | 实际结果 |
| --- | --- |
| 旧 handoff unknown → 顾问核查未发布 → retry → 设备同步 | 先触发账号等待；错误 tuple/403 不解除。正确 proof 独立持久化，新 task/grant/lease 实际进入 awaiting-human。unknown 由受控执行器异常触发，新尝试使用实际 HumanHandoffExecutor。 |
| 实际 HUMAN_REQUIRED → 离线 grant/lease 过期 → 顾问核查 → retry → 同步 | 顾问在没有旧设备 exchange 的情况下核查过期尝试。MHT 读取原 awaiting-human tuple 的明确证明，新任务实际进入 awaiting-human。 |
| 历史不兼容发件箱 | 834 客户端真实产生 ACCOUNT_INTERVENTION_REQUIRED 待发项。最终客户端保留其原字节、原审计及 outbox 行，以独立隔离表停止发送；新等待项不污染 frozen-v1。中央码表原样保留，真实中央对此码返回 403 receipt_scope_mismatch。 |
| 设备只读调查证据 | 未核查时 null；已核查时精确 tuple 的 advisor-reported 否定证明。错 task/grant/lease/customer/project/account/version/digest、JWT 冒用、绑定撤销被拒绝；重复读取没有业务写入。 |

两条恢复链均断言：旧 receipt/audit 逐条不变；旧授权失效；新内容版本/摘要不变；新任务仅执行一次；旧槽位 released、新槽位 held；最新合法回执得到真实中央 ack；重启后不重执行、不新增回执/审计，也不重复读取已保存证明的旧 task。新 awaiting-human task 继续读取自己尚未核查的 null 结论是有效行为，按 taskId 区分。

负例中的 403 与损坏 echo 由测试包装器在真实中央鉴权读取后注入，null 来自真实未核查接口；最终设备读取授权拒绝由真实中央规则验证。没有把模拟响应当作真实发布证据。

此前正常交接链已在 `ba65dbeaf7a53c01cde759104e55562acbaa1c09` + MHT `808304d132e4114263cef597c04126a7cec8125f` 上验证注册、续期、HUMAN_REQUIRED、人工完成辅助回执、SQLite outbox ack、中央槽位 consumed、能力撤销。证据仍保留原版本，依本次范围没有重复全量或正常链测试。本次最终代码的 SEO/GEO 实际 assembled CLI 各运行一次，计量和控制开启；空隔离 schema 零任务、零规划请求、零 AI 事件。这是入口检查，不是有数据的原生全流程验收。

## 状态与未验收范围

本地交接候选支持经审批固定版本的 preflight/handoff；12 渠道目录和实际内容类型保留，v1 可执行交接平台仍只有 wechat-article/xiaohongshu-image。素材交接完成不代表已发布；publish 必须使用独立明确确认及授权。

真实平台的账户登录、素材上传/填写、提交和公开发布回执尚未联测；平台自动填写/上传/提交继续关闭。生产部署、生产数据库迁移、真实资金/SEM、付费 AI 调用均未执行。历史 834 恢复失败已保留在最终证据中，不能用正向单例通过覆盖它。

临时 TLS 服务与测试 SQLite/证书已清理。本窗口拥有的 55443 PostgreSQL 已停止，数据目录保留供复现。MHT、SEO、GEO 外来工作树只读，没有构建、Cookie/profile 或真人账号操作，没有重启用户当前程序。

## 复现

使用本项目 `D:/SNIPERS国内版/ai_sni/.venv/Scripts/python.exe` 和独立 55443 测试库（distribution_test/distribution_control_test）。先按 MHT 冻结清单核 SHA 并复制完整产物到私有 TEMP 快照，snapshot.json 应记录 source_commit/artifacts/fixtures。

设置 `DISTRIBUTION_TEST_DATABASE_URL`、`DISTRIBUTION_MHT_FROZEN_SNAPSHOT`（最终 bd8）、`DISTRIBUTION_MHT_LEGACY_SNAPSHOT`（历史 834）、可选 `DISTRIBUTION_RECOVERY_PROOF_DIRECTORY`（TEMP）。运行：

```text
python -m pytest tests/test_distribution_capability_registration.py -k "frozen_mht_unknown or device_resolution_read" -q --tb=short
```

最终测试脚本及其 SHA 已随验收代码冻结；凭据仅由测试经子进程环境传递，没有进入参数、stdin 或证据文件。

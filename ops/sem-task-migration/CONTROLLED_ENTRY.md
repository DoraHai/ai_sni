# 受控入口实现草案（未批准用于生产）

入口 `controlled.py`、专用环境 `controlled/env.py` 与现有本地入口分离。
不加入任何 workflow，不安装服务器脚本，不读取应用 .env，不重新配置角色/权限。
开发测试只连接一次性本地库；生产调用另行审核并授权。

## 功能与信任边界

- `fingerprint`：离线计算只读 JSON 报告的原始文件摘要和结构摘要，不代表审核通过。
- `check`：离线校验审批材料、有效窗口、干净的获审 Git checkout、获审源包、唯一迁移图、
  数据库元数据基线。不连接数据库；输出 passed 不代表备份/停并发已落实。
- `apply`：独立生产入口候选，Unix-only，需额外提供 owner-only 凭据文件与全新审计回执路径。
  使用系统信任库验证数据库 TLS，固定 public、起点 0094、目标 0095，拒绝 query 参数覆盖。
  不提供 head/stamp/downgrade/任意 schema/关闭 TLS 开关。

复用旧源包的 **已验字节和版本文件**，但不执行其中的本地 env.py；改用本受控 env。
源包的 `local-rehearsal-only` 标记仍保留，不能拿旧 local-upgrade 执行生产。
生产授权绑定的是本新入口获审提交、旧源包 MANIFEST 摘要和独立审批材料的组合。
构建后移交必须保留这些来源，不把单个源包目录称作独立获准的生产执行器。

完整源码 Git checkout 与源包放在独立、仅操作者可写目录，不能放/改应用 releases/current。
入口要求 HEAD 精确等于审批提交，拒绝脏文件和未跟踪文件；无关的工作区改动也不允许。
所有文件在执行窗口内不得并发修改。无签名服务：审批 JSON + 人工核验摘要并不能对抗
有能力修改工具、审批和 SHA 参数的同一运维身份；真实授权、材料核验属于外部变更管理。

## 审批 JSON 契约（由负责人审核，禁止自行用占位值执行）

必填字段：

| 字段 | 要求 |
|---|---|
| confirmation | `MIGRATE_SEM_TASKS_0095` |
| schema / start_revision / target_revision | `public` / `0094_seo_qa_batches` / `0095_sem_tasks` |
| checkout_commit | 包含入口代码的获审完整 40 位小写 SHA |
| manifest_sha256 | 构建后的 MANIFEST.json 原始字节 SHA-256 |
| baseline_sha256 / schema_sha256 | 完整只读 JSON 原始字节摘要 / 本工具规范化结构摘要 |
| not_before / expires_at | 带时区 ISO 时间，窗口不超过 1 小时，过期拒绝 |
| database | host、port、name、role、server_address、server_port 全部明确；无密码 |
| application_role | 必须等于 database.role；不同角色/GRANT 方案本版不支持 |
| change_id / operator / reviewer | 外部变更单、执行人和审核人记录 |
| backup_evidence / restore_evidence / pause_evidence | 已核验备份、恢复演练、暂停共享并发变更的证据引用 |
| schema_review_evidence / seo_compatibility_evidence | 结构审核与已部署 SEO 兼容性证据引用 |
| seo_release_commit / seo_rollback_commit | 均为完整提交，两个产物均须兼容 0094/0095 |
| seo_release_sha256 / seo_rollback_sha256 | 对应获审产物 SHA-256 |

程序检查必填、类型、摘要和时间窗口，**不能证明引用的外部备份/发布记录真实有效**。
审核人必须核对内容，不是随手填写任意字符串；不提供生成有效生产审批的模板或快捷开关。
审批文件本身也必须在执行前通过独立渠道核验 SHA-256，禁止取未经审核文件现场自算后直接放行。

生产只读报告必须来自同一角色；本版要求执行角色就是应用角色（是否使用 sem_app 仍待批准）。
不会自动创建专用角色，也不默认为某账号提权。程序在连接后核验实际库名/角色/服务器地址端口，
数据库端地址在代理/故障切换场景可能变化：此时拒绝，重新核对，不提供忽略身份参数。

## 接口示意（路径占位，不是当前执行授权）

```text
python -I -B ops/sem-task-migration/controlled.py fingerprint --baseline <只读JSON>
python -I -B ops/sem-task-migration/controlled.py check --baseline <只读JSON> --approval <审批JSON> --approval-sha256 <独立核验摘要> --bundle <源包目录>
```

未来明确授权的生产调用为同一接口 `apply`，额外要求 `--credential-file` 与 `--receipt`。
凭据文件仅包含数据库 URL，Unix 当前用户所有、无组/其他权限、正规文件、拒绝链接/硬链接；
不用明文 URL 命令参数或环境 DATABASE_URL。操作者通过已获准保密渠道准备，凭据生命周期
由运维流程负责；工具不复制、不修改、不删除共享 .env。TLS 信任不符时停止，不降级明文。

审计回执必须是新文件（O_EXCL，0600），记录审批摘要、提交、阶段、时间，不记录连接串。
事务开始、待提交、提交获确认均落盘；失败统一标记结果未确认，需只读复核，不自动重试。
网络中断发生在 COMMIT 时可能已提交，不得将异常一律宣称“已回滚”。回执写入失败同样停止。

## 数据库侧步骤

校验输入 → 新连接 → 总超时最多 60 秒且不超过审批有效期 → 事务 → 锁版本表 →
核验身份/唯一单行版本/对象冲突/权限/租户 BIGINT PK → 与获审结构比较 → 唯一 Alembic 0095 →
检查版本、既有结构不变、新字段类型/空值、主外键、CHECK 名称、索引有效、owner/权限及空表 → 提交。

1 秒锁超时、10 秒语句超时是本版固定上限，生产采用前必须审核适用性；不支持现场传参放宽。
显式 pg_temp 放在末尾并拒绝现存临时对象，Alembic 建表阶段只向 public 建表。
不手改版本行，不改客户行。数据库 CHECK 只能检查证据形状/非空，不证明指标证据真实。
版本表锁不能排除不合作的外部 DDL；负责人确认停并发仍是不可省略的运维前提。

结构基线仅覆盖 preflight 脚本所列目录元数据，不是全库备份/全对象一致性证明。
本轮新表后验也不替代人工审查 CHECK 语义及完整 DDL；迁移文件和摘要必须事先审核。

## 发布前仍未完成

- 正式审批人、执行角色、环境路径、备份恢复证据与停并发控制权确认。
- 完整生产结构对账、生产 TLS/文件权限适配及受控环境验收。
- 审核、单独批准并先部署 SEO 兼容版；GEO 无需本次部署。
- 独立批准生产迁移；SemTask 继续关闭，启用另行批准。

没有上述批准，不得运行 apply。代码存在不代表已经安装或具备生产执行权限。

## 本轮验证

- 受控入口专项：31 passed、1 skipped。跳过项为 Unix 凭据文件权限/链接测试，
  当前 Windows 本地环境不能代替该项；已纳入测试，须在 Linux CI/受控环境确认。
- 7 个原生 PostgreSQL 场景在随机一次性本地数据库执行：成功、重复、结构漂移、错误版本、
  名称冲突、建表后注入故障、身份不符。实际 Alembic 事务成功与失败后的数据/版本均核验。
- 扩大回归：1886 passed、1 skipped、1 条既有 jieba 警告；之后补的两项提交确认测试
  已包含在最终 31 项专项结果中。扩大回归排除既有 SEO migration merge 与 foundation/
  writeback_health/postrelease 三组其他专用 PostgreSQL 文件。
- 此测试验证事务内核和本地源图，不是生产 TLS/Unix 凭据适配器端到端验收。
  生产端身份、实际权限及外部审批材料均未验证。
- 随机临时数据库已清理，仅删除测试 fixture；本地 PostgreSQL 已停止。
  无生产连接、无生产 Alembic、无部署/重启/开关变更。

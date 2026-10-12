# 首次设备配对后端交接

已完成一次性配对后端和设备自身绑定发现接口。超管网页仅获取短期code，公司电脑直接HTTPS领取独立设备credential；领取不授予账号、项目、capability或发布grant，项目/账号仍由超管明确绑定。默认pairing和remote control都关闭，正式发布仍关闭。公司电脑GUI、标准网页和公开独立验收部署由总控继续，本报告不能替代真实微信发布验收。

## 精确提交

新工作树 `distribution-device-pairing-20261012`，基线 `30ab07bbd2a08b3612c6e0f2946ccd3f26449fae`。顺序cherry-pick：

1. `98a39f82d025e702a01f3139ba046a5427cce38e`：合同和fixture。
2. `9ec7eded2fd6e740b1c548c9fb969ac6500bf47d`：响应schema字段必须存在、secret模型repr隐藏。
3. `cf8fd1e4171bec5ae19a7cc1ec1db6752909672e`：业务实现、独立SQL及真实测试。
4. `577caf134a13fa698451ede514d63d5b04323812`：仅测试观察器刷新PG统计快照的一行，不改业务。

业务冻结cf8，最终测试/运行pin577，tree `ab9166691e9d7d5210f32dfc0a22d90d37b62c5b`。后续证据提交仅docs。可运行文件SHA已从actual HTTPS health核对6项，与工作树一致。

生产范围仅新 `app/distribution_pairing_contract.py`、`app/distribution_pairing.py`、`app/api/distribution_pairing.py`，原 `app/api/distribution.py`新增pairing router、feature开关下旧设备创建拒绝、设备撤销hook。共享auth/models/main、SEM、SEO/GEO原生业务和旧冻结树未修改。新SQL `scripts/distribution_device_pairing_schema.sql`只建 `distribution_device_pairings`，仅在自有PG55547随机namespace执行。

应用沿用原distribution router挂载，无新lifespan。验收环境明确设置 `DISTRIBUTION_DEVICE_PAIRING_ENABLED=true`；仅严格true启用，默认off保持旧POSTdevices兼容。flag=true时旧POSTdevices为409 `DEVICE_PAIRING_REQUIRED`，网页不会得到长期credential。remote开关独立默认off，测试为验证撤远程明确on。

装配/打包manifest需加入上述3个模块、SQL及合同fixture。PC接口、字段、时间单位、错误与GET范围见 [DISTRIBUTION_DEVICE_PAIRING_V1.md](DISTRIBUTION_DEVICE_PAIRING_V1.md)，权威JSONschema为 `docs/fixtures/distribution-device-pairing-v1.json`。claim必须PC main进程发无Authorization/Origin/Sec-Fetch头的HTTPS JSON请求，禁止URL传码或自动重试未知领取。

## 行为与边界

code随机192bit/32字符、最长600秒，默认300秒；DB只存SHA。创建预留inactive device，同超管最多10个未过期pending。重复创建request拒绝，不补发code。PC领取一次事务中重核原创建者当前超管权限与截止时间，生成独立384bit/64字符credential、激活device、消费码和追加metadata审计。权限锁等待跨TTL也拒绝，不延长码期限。重复、过期、撤销、未知码或创建者失权均不回放credential。

领取响应未知时，PC保守停止，超管撤销原配对/设备再新配对。新配对ID和device ID独立。通过配对撤销或旧device-revoke入口，都不能重新激活pending预留设备；已领取设备也停用，remote清nonce/PNG/输入/历史并关闭，caps失活，任务按原规则queued取消或在途unknown，不把未知结果改成未发布。

设备只用自己的Bearer查询 `/api/distribution/v1/device/bindings`，不领取超管JWT。返回本设备至多50个active wechat绑定的窄metadata和external_account_id；逐范围重新走原生当前顾问与项目运营授权。跨device、错误凭据、服务/指派失效拒绝或移出结果，结构/DB故障503而非伪空成功。最初0条，绑定后 `login_state=unverified`，需要真实微信身份核验；配对不声称账号已登录。

## 实际测试

自有trusted HTTPS55881、PG55547，原生SEO固定 `b4d8387123355348f79e26ea2838585c5106a4b9`，真实0105 migration和原生JWT。22不同用例在最终同一focused运行全部通过，无跳过：

- 当前实名超管、客户/顾问拒绝、撤超管权限、严格字段/TTL/大小/query/HTTPS代理scheme检查、网页Origin/JWT/Sec-Fetch拒绝、无秘密GET。
- 8并发claim仅1成功；claim与revoke竞争后device仍失活；过期、重复、pending设备经旧入口撤销不复活；真实issuer角色写锁等待跨TTL拒绝。
- 错device/超管JWT不能发现PC绑定；本设备范围、external身份、未核验状态准确；网站/模块停用或顾问撤销移出；缺原生结构503。
- 审计和commit真实PG错误验证create/claim原子回滚；未知领取后明确超管撤销、新配对，不凭同码重领。
- 真实原生SEO创建、独立审核、顾问版本确认、非AI适配、渠道审核、actual source、leased preflight任务，加真实caps注册和remote已读画面/待输入：撤销后task revoked且unknown、publication grant为空、remote关闭/命令canceled、caps inactive，旧凭据401。
- 重启保留未消费码，已消费码不重放credential；默认off实例不抢remote owner、旧POSTdevices兼容；PG和普通日志无测试生成的plaintext code/credential。

早期3个测试前提/观察错误均保留原始XML：恢复测试角色遗漏SEO权限导致后续原生403；错误期待旧bind响应含external标识；PG长事务缓存观察快照。修正只涉及测试，没有降低原生门禁。最终完整22项绿色XML SHA `514d59277665ba7d0642203c1ab6e99bbe0aeccfab51667954519b87460b8154`。没有重跑历史remote/SEO/GEO大套件。

最终PG只读检查paired devices、remote sessions、paired caps均无active，三轮测试保留的3个合成leased任务均保持revoked/unknown，原生版本0105正确。证据 [DISTRIBUTION_DEVICE_PAIRING_EVIDENCE_20261012.json](DISTRIBUTION_DEVICE_PAIRING_EVIDENCE_20261012.json)记录运行hash和所有历史/最终XML SHA；原始文件仅在私有TEMP `distribution-device-pairing-tests-20261012`，不提交password/code/credential/响应正文。

未实测公司电脑GUI首次配对和安全保存凭据、标准超管网页、GEO原生discovery全链、公开验收环境部署或真实微信登录/发布。scope/身份正例为合成客户数据；未使用生产数据、生产DDL、GitHub推送或部署。

收尾已停止本窗口自有PG55547和HTTPS55881/55882，三端口核无监听，私有数据/证据保留。没有停止总控pilot、其他验收环境或生产服务。

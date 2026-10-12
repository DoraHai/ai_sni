# 首次一次性设备配对 v1

公司电脑多号通通过HTTPS主动领取独立设备凭据；超管网页只显示短期一次性码。身份不授予客户、项目或账号访问：领取后仍无binding/capability/grant，由超管另经现有绑定入口明确选项目与账号。首轮只验收wechat-article，SEM不变。remote control开关默认关闭。

前缀 `/api/distribution/v1`。字段严格snake_case、extra forbid、UUID字符串、UTC epoch毫秒。所有响应no-store/nosniff，禁止query参数，JSON请求最多4096 bytes，错误只含固定code、不回显请求。所有端点要求HTTPS；反向代理需由可信连接正确传递scheme。

| 端点 | 身份 | 请求 | 响应 |
| --- | --- | --- | --- |
| POST `/device-pairings` | 当前实名超管JWT | `{label,expires_in_seconds?:300,request_id}` | `{schema:1,pairing:PairingView,pairing_code,code_once:true}` |
| GET `/device-pairings` | 当前实名超管JWT | 无query | `{schema:1,items:[PairingView],as_of}`，最近20条 |
| GET `/device-pairings/{id}` | 当前实名超管JWT | 无query | `{schema:1,pairing:PairingView}` |
| POST `/device-pairings/{id}/revoke` | 当前实名超管JWT | `{request_id}` | `{schema:1,pairing:PairingView}`；关联device也停用 |
| POST `/device-pairings/claim` | PC持有一次性码，无JWT | `{pairing_code,request_id}` | `{schema:1,pairing_id,claimed_at,device:{id,label,active:true,credential,credential_once:true},bindings_configured:false,automatic_submit:false}` |
| POST `/device/bindings` | PC当前device Bearer，无超管JWT | `{device_id}` | `{schema:1,device_id,as_of,items:[DeviceBindingView],automatic_submit:false}` |

label为1–80字符，不接受空白或控制字符。expires_in_seconds严格整数60–600，默认300。code为服务器随机192bit生成的32位URLsafe字符串，区分大小写；credential为独立随机384bit生成的64位URLsafe字符串，与现有device Bearer验证兼容。Pydantic权威源为 `app/distribution_pairing_contract.py`，JSONschema fixture为 `docs/fixtures/distribution-device-pairing-v1.json`。

`PairingView`严格只有 `{id,request_id,device_id,label,state,created_at,expires_at,claimed_at,revoked_at,automatic_submit:false,bindings_configured:false}`；state为pending/claimed/expired/revoked，两个动作时间可null。bindings_configured描述此配对动作不配置binding，不代表后续绑定的实时状态。GET永不返回code、code hash、credential、credential hash或客户内容。

`DeviceBindingView`严格只有 `{binding_id,device_id,module,tenant_id,scope_id,account_id,external_account_id,platform:'wechat-article',login_state:'unverified'}`。最初items为空，超管明确绑定后才可发现；只读取当前Bearer对应device的active绑定，重新经原生模块当前顾问/项目运营权限核验，失活、服务过期或撤权的范围不会返回。最多核验本device的前50条wechat绑定，范围错误不能读取其他设备绑定。此metadata不包含credential/cookie/超管信息/文章；未核真实微信身份前统一unverified，不能声称已登录。结构或数据库异常503，不能假装返回空列表成功。

创建时预留inactive device，网页只收到code；重复创建request UUID返回409 `PAIRING_CREATE_ALREADY_EXISTS`，不补发code。列表可按request_id核对未知创建结果；丢码必须撤销旧配对再创建新码。

claim只接受公司电脑main进程HTTP调用，拒绝Authorization、Origin和Sec-Fetch请求头，防止浏览器页面把PC领取入口当成凭据下载API。码只放JSON，禁止拼入URL；电脑验证HTTPS证书，不使用全局TLS忽略。PC不得记录码、credential或响应正文，不应自动重试claim。任何重复、过期、撤销、未知码或已失权创建者均409 `PAIRING_CODE_UNAVAILABLE`；不回放已领取凭据。网络超时或领取响应未知须提示超管撤销该配对/设备并重新配对。只有成功响应后才保存本机安全凭据；绑定仍必须由超管明确确认。

服务端一次事务锁定预留device及配对记录，重新检查创建者当前超管权限，生成凭据、激活device、消费code和追加元数据审计原子commit。撤销连同关联device使用当前设备撤销路径：停用设备、撤销任务及释放符合原规则的保留额度，未知执行结果保持unknown。不会恢复grant或正式发布许可。

`DISTRIBUTION_DEVICE_PAIRING_ENABLED`默认关闭，仅值严格为true启用。开启后旧POST `/devices` 返回409 `DEVICE_PAIRING_REQUIRED`，避免网页继续领取长期凭据；原GETdevice/bindings与权限门禁保留。SQL只新增 `distribution_device_pairings`，只在独立验收namespace执行，本轮不执行生产DDL。

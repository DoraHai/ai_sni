# UI15 客户与顾问站内沟通

2026-10-08。本批负责 customer-workbench 产品、客户端、定向测试和文档；宿主入口、CI、ops由总控独立维护。没有推送、合并、部署或生产读写。用户已解除此前额度暂停限制。

## 交互与契约

打开稿件后出现默认折叠的“本稿件对话”，标题绑定当前稿件。其他页面提示先打开稿件。展开可查看服务端实名、角色、时间和纯文本消息，向旧历史分页，刷新新消息并发送文本。发送消息、客户确认、顾问审核三个动作互相独立。没有AI、附件、外部通知或模拟发送。

前缀 `/api/v1/seo/workbench/content-assets/{content_id}/conversation`，沿用当前宿主JWT及授权tenant/site。GET前缀读取资格、会话与未读摘要；GET `/messages` 使用limit=20及before_id向旧分页，页面内按ID升序；POST `/messages` 只提交tenant_id、site_id、request_id和body；POST `/read` 只提交tenant_id、site_id和last_read_message_id。精确响应按照SEO的UI15契约校验，不能用客户端填写sender/time。

已读由用户展开后点击“标记本页及更早消息已读”推进；GET、展开、发送均不会自动标读。它是单调游标，按钮明确包含更早消息。无后台轮询，使用刷新读取新消息和未读数。

发送前生成UUID，等待和未知结果期间锁定同一文本/UUID；失败保留文本，用户重试复用同一键。只有合法成功响应才清空输入，成功后刷新失败会明确说“消息已发送，但记录刷新失败”。422验证失败允许改字重新发送。20秒请求超时保留待核对状态。不把未知结果当作成功，也不自动重放。正文、待发文字和重试键仅保存在当前页面内存，刷新前有未发送提醒；不写新凭据或消息存储。

切客户/站点/稿件、登出、401/403或观察到顾问资格撤销时清理会话、输入和待发键；异步旧范围响应丢弃。普通离开稿件有未发文字时提供放弃提示。权限仍由服务端每次核验，客户端角色标记不能授予发送资格。

## 定向检查

- `npm run test:contracts`：消息客户端测试纳入现有CI门禁，含提交后丢响应、同键恢复、范围切换拒绝旧待发内容、跨scope请求拒绝和错误元数据拒绝。与既有契约共32项通过。
- `npm run test:ui15`：包括消息契约、浏览器交互、构建产物入口检查。夹具覆盖25条历史、未读不自动推进、显示HTML原文而不执行、失败输入保留/同键重试唯一记录、确认记录不被更改、切身份/客户/403清空和390像素无溢出。首次断开连接用例会触发浏览器透明重试，改为提交后明确返回错误，最终该浏览器场景通过。
- 实际production-entry构建产物保留现有登录redirect；缺失、非法或重复tenant/site参数不发业务请求；客户绑定tenant不受URL改写，异站范围拒绝；401清除原会话并返回准确scope登录。缺少scope时仍通过“返回现有工作台”选择，不重建登录或选择器。宿主入口由总控提供参数。

原LoginView验证码整页、生产账号与部署不属于这些本机夹具结果。

## 真实隔离环境执行

后端0106和UI15专用合成稿件交接就绪后，运行 `scripts/ui15-real-messages.mjs`。该脚本只允许登录及指定稿件消息/已读写入，不允许确认、发布、AI、采集或旧UI12/14写流程。凭据只从系统TEMP的既有配置加载，不入库。

```powershell
$env:UI12_CONFIG_FILE='<SEO交接的绝对配置路径>'
$env:UI15_REAL_API_AUTHORIZED='true'
$env:UI15_CONTENT_ID='<UI15专用稿件ID>'
$env:UI15_SECONDARY_SITE_ID='<SEO提供的第二站点，可选>'
$env:UI15_REVOKE_HANDSHAKE='true'
npm run build
node scripts/ui15-real-messages.mjs
```

计划新增3条合成消息：客户意见、顾问回复、客户幂等恢复；最后一条在服务器返回后故意丢弃成功响应，再用相同UUID重试。两身份刷新读取，客户reload验证持久化，历史预置超过20条以免为分页大量写测。脚本输出TEMP报告与桌面/手机截图。

撤权握手由SEO维护隔离库：脚本保留顾问未发送文字，写出revocation-ready.json；SEO撤销assignment后写revoked.json；浏览器验证403清空并写revocation-tested.json；SEO恢复assignment并写restored.json，最后重连读成功。前端不直接操作DB。真实结果和准确构建SHA在完成后的交接回报中记录；本节执行说明本身不代表真实环境已经通过。

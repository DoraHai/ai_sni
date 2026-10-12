# 首次设备配对与顾问账号流程（合同前设计）

独立树：D:/SNIPERS国内版/ai_sni-worktrees/advisor-device-pairing-20261012。
分支：codex/advisor-device-pairing-20261012。已验共同页面基线30ab07bb，保留eb299187 close-only修复及root已验14渠道目录。本树产物仍使用customer-workbench原build独立dist，不覆盖原冻包。

## 已核对入口

超管 /customer-workbench/?console=platform → [data-pc-page=distribution] → platform-console-view.mjs 的 mountDistributionAdmin，现实现位于distribution-panel.mjs。
旧创建设备表单 data-distribution-admin=device 调用distribution-client.createDevice，返回device.credential并在textarea临时展示。新的首次配对流程必须替换这个浏览器长期凭据路径，不能在其上叠加短码后继续泄漏credential；后端兼容策略由owner明确。
超管既有devices/bindings/account policies/events读取和权限边界保留。创建码、码状态和撤销端点等待权威合同，前端不猜API。

## 拟实现流程

1. 超管填写公司专用电脑名称，明确创建“短期一次性配对码”。仅显示服务器返回短码和有效期；复制动作由用户点击，失败提供只读手工选择。禁止自动复制、日志、URL、localStorage/sessionStorage持久化。
2. 显示有效、已使用、过期、已撤销或结果未知，以服务端状态为准。码过期/退出/撤权/切页立即清除网页中的码与异步结果。创建结果未知不自动再创建；撤销不代表电脑账号登出或稿件发布。
3. 专用电脑安装/运行执行端并输入短码（执行端配对及credential本地安全保存由owner负责）。网页只能看到设备配对和最近联系状态，不接收长期device key。
4. 超管按真实授权客户/网站/项目绑定账号。先wechat-article；其余渠道目录保留，不把未接入渠道说成可发布。
5. 顾问在已分配项目选择绑定账号，分别显示“设备绑定/服务端联系”“平台登录待核验”“当前版本素材交接”“公开发布待核验”。账号绑定或远程会话active都不代表已登录或已发布。
6. 顾问远程登录/验证码/任务异常入口沿用nonce闭包、scopeepoch、串行status/PNG、新鲜帧及close-only。结果未知仅可显式关闭控制，不能自动重发或恢复任务。

稿件来源沿用SEO/GEO产出或导入。网页核对并批准当前版本，选择已配置账号渠道；不能通过按钮把未有真实公开页面证据的稿件标成已发布。真实一账号一渠道发布与独立验收部署由root协调，本UI分支不部署/push、不执行DDL、不修改SEM/shared login/backend/运行环境。

## 待合同与验收

等待backend提供精确pairing请求/响应、TTL/state/nonce或撤销前提/幂等策略、权限及禁device credential的返回规则。收到后实施独立client/view及DOM测试，按最小增量接现有admin入口。
必要测试：非超管不得创建/撤销，短码到期/撤权/切页/迟到清理，复制只由用户触发，credential字段拒绝并不渲染，无供应器诚实未接入；顾问绑定状态和客户无控制回归；原标准4文件build与产物hash。当前只完成只读核对与设计，没有声称配对UI或API已可用。

## 已实现前端增量（权威9ec7eded合同）

已只读核对app/distribution_pairing_contract.py、docs/fixtures/distribution-device-pairing-v1.json和说明，不挑取backend提交。device_id按Identifier校验，GETlist含as_of；PairingView exact字段拒绝credential/code/hash等新增字段，create仅接32位URLsafe一次码。client仅固定create/list/revoke，网页不调用claim/discovery。

原超管分发页替换为创建/复制/有效期/metadata刷新/撤销配对入口；旧createDevice仅本地抛DEVICE_PAIRING_REQUIRED，原长期credential响应读取和textarea已移除。未知create用request_id锁住重复创建，先核对并撤销对应记录；短码不持久化，过期/权限/换账号/切页dispose清除且拒绝迟到响应。原项目+平台账号binding及账号规则仍在。

顾问remote说明已调整为选择当前账号→扫码/验证码介入→关闭控制，明确pair/bind/login/material/publicpage各自核验。没有新发布成功按钮，close-only修复保留。首轮公众号文章验收与其余渠道候选边界不变。

验证：新增client4项+DOM1项通过；原标准编译超管页“短期码暂存、切页清理、个别账号绑定/停用”1项通过。夹具仅用于测试，模拟PC领取后的设备状态不能算真实claim验收。标准customer-workbench4文件build通过；SEM verify结果另见交付消息。新tree dist独立生成，原30ab/eb冻包未修改。真实PC claim/JWT/绑定和真实平台单账号单渠道发布仍由root独立验收环境协调，本分支未deploy/push/DDL。

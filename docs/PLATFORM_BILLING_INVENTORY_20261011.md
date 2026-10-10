# 超管账务与套餐展示

本补充以 #649 c71d6b20 后端、#646 69cc9703 前端为依赖，各自独立提交，不改两份固定候选。只新增只读余额查询与用户提供的 dated 观察数据，无生产 DDL、模型调用、付款或开关修改。

## 查询与口径

`GET /api/v1/admin/console/balances` 保留 schema 1，新增可选 provider `volcengine/tencent/qianfan/kimi/dataforseo`。未指定 provider 时全平台查询，百度推广继续按 10 个账户分页。全局具名管理员鉴权、private/no-store、Vary Authorization、固定地址、5 秒 HTTP / 8 秒总超时、64 KiB 云响应上限、禁代理和跳转、60 秒缓存和 5 秒手动查询冷却沿用；请求参数不能指定地址。

- 火山引擎 GET `https://open.volcengineapi.com/?Action=QueryBalanceAcct&Version=2022-01-01`，billing/cn-north-1 V4 签名，返回 AccountID、AvailableBalance、CashBalance、CreditLimit、FreezeAmount、ArrearsBalance。
- 腾讯云 POST `https://billing.tencentcloudapi.com/`，TC3，Action=DescribeAccountBalance、Version=2018-07-09。真实可用余额只用 RealBalance，所有资金从分换算元，赠额/现金/信用/冻结/欠费分列。没有 finance:trade 操作。子用户只加自定义 `finance:DescribeAccountBalance`；账单只读策略不被假定包含余额权限。
- 百度智能云 POST `https://billing.baidubce.com/v1/finance/cash/balance`，BCE V1 host/x-bce-date 签名，cashBalance 明确为现金余额，不宣称含赠额或资源包，区别于百度推广账户。
- Kimi / DataForSEO 固定官方读接口。显式配置可在 controls 未启用/数据库不可读时查询；不从独立服务环境自动偷取密钥。现有托管连接仍遵守 controls 的授权门槛。同凭据去重，多个凭据不等于多个扣费账户，不汇总总金额。

云账户与模型连接的扣费归属仍需核对，coverage.billing_link_state=account_to_verify。查询成功的账务账号不自动证明每个模型 Key 属于该账号。可配置火山 AccountID、腾讯 UIN 与供应商返回比对；不一致不展示金额。百度 cash 接口没有账号身份字段，不捏造验证。

## 仅后端配置

所有密钥字段 repr=False，仅由 SEM 后端的安全环境配置读取，不进前端/日志/JSON：

| 平台 | 环境变量 |
|---|---|
| 火山 | VOLCENGINE_BALANCE_ACCESS_KEY_ID、VOLCENGINE_BALANCE_ACCESS_KEY_SECRET；可选 VOLCENGINE_BALANCE_ACCOUNT_ID=2131454985 |
| 腾讯 | TENCENT_BALANCE_SECRET_ID、TENCENT_BALANCE_SECRET_KEY；可选 TENCENT_BALANCE_ACCOUNT_UIN=100052496461 |
| 百度云 | QIANFAN_BALANCE_ACCESS_KEY_ID、QIANFAN_BALANCE_ACCESS_KEY_SECRET |
| Kimi | KIMI_BALANCE_API_KEY |
| DataForSEO | DATAFORSEO_BALANCE_LOGIN、DATAFORSEO_BALANCE_PASSWORD |

仅账户所有者确认的专用查询凭据可配置。不用模型 Key 代替云账务 AK/SK，不自动回退主账号密钥。附件只有保险柜条目名，开发机器目前无保险柜连接，不能声称新凭据已配置或已在生产测通。

## 人工数据

`config/platform_billing_observations.json` 是用户 2026-10-11 汇总的完整 9 项站长之家套餐、账户余额、4 家授权测试金额和本次腾讯账号的 WSA 未开通记录。没有密钥/手机号/微信。其数据由 `observations` 独立字段返回；不成为 available 的实时余额、不使用当前查询时间覆盖核验日期、不参与实时金额预警。

日期为北京时间核验日，未伪造具体时分。核验日过去后 freshness=needs_recheck。余量提醒为核验时状态：0 次耗尽，剩余占总量不超过 10% 为低，其余正常；247/250 和 9/10 均正常。到期日实时计算是否到期或 30 天内到期，但余量仍需重查。WSA 是所核验账号未开通，不据此覆盖系统搜索 Key 配置。

可用 PLATFORM_BILLING_OBSERVATIONS_PATH 指定后端控制的本地 JSON（不是请求参数或 URL），便于后续核验更新。文件最多 64 KiB，白名单投影；数值不守恒/负数/重复套餐/未来核验日/无效结构均独立显示不可读，实际云查询继续。更新人工文件应原子写入，目录权限限定管理员；刷新接口只读。

无已验证的官方站长之家余量查询实现，不用付费数据探测扣额度，不读浏览器 Cookie，不将本地调用账本推算为余量。用户核验余额 ¥0 与仍可用套餐分别显示。

## 验证与上线验收

三家签名已用公开 dummy key 与官方独立 SDK 全请求签名对照：volcengine 1.0.228、tencentcloud-sdk-python-common 3.1.187、bce-python-sdk 0.9.79。仅装临时目录用于对照，应用不新增 SDK 依赖；冻结向量进测试。MockTransport/接口桩测试验证零余额、负余额、单位转换、缺失字段拒绝、只读固定 Action、返回账号不一致、供应商错误脱敏、401/403 无供应商查询、无 controls/DB 云直查、失败不回填历史金额。原有两项 PostgreSQL 原生隔离测试必须零跳过。

生产验收顺序：取得保险柜安全访问方式；配置专用环境密钥和账号校验；通过既有 Git 发布链路发布后端及独立 workbench 前端；逐 provider 人工核对控制台最新金额及返回账号、权限失败/未配置/零余额显示；检查 9 项人工套餐和日期、WSA 核验说明、5 分钟可见页面刷新及手动查询。当前没有对新云凭据做生产测试。前后端可兼容缺少 observations 的旧 schema 1 返回，但旧前端不会展示新增人工区。

参考：[火山余额接口](https://docs.volcengine.com/docs/6269/1223898?lang=zh)、[火山签名](https://www.volcengine.com/docs/6269/130258)、[腾讯余额](https://cloud.tencent.com/document/api/555/20253)、[腾讯只读 CAM](https://cloud.tencent.com/document/product/555/61542)、[百度余额](https://cloud.baidu.com/doc/Finance/s/Skhtyytwu)、[百度签名](https://cloud.baidu.com/doc/Reference/s/njwvz1yfu)。

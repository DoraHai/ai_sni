# SEM 纯查询消费包

这是交付给工作台负责人的ES模块和**虚构测试样例**，不启动网页、不提供默认网络连接。
当前驾驶舱原型不修改。服务身份/模块资格及实际部署版本确认后才能接真实transport。

```js
import { createSemReadonlyClient } from './readonly-client.mjs'

const sem = createSemReadonlyClient({
  transport: authenticatedSemTransport, // 工作台经确认的用户身份传递；返回Fetch Response形状
  onClear: clearSemViewsAndConversationContext,
})

// 只用已完成的当前客户/用户/模块资格判断结果，不用演示配置。
sem.setContext({ tenantId, userId, authorizationRevision, allowedReads })
const report = await sem.read('report', {
  start_date: '2026-09-01', end_date: '2026-09-03', baidu_account_id: selectedAccountId,
})
// all模式省略baidu_account_id，不能传null或偷偷传首个账户。
// 客户切换/登出/权限刷新失败：
sem.invalidate()
```

上例transport、清理回调及身份变量是**待工作台注入的依赖**，不是已实现的AUTH-01/ID-01服务。
transport接收相对SEM路径以及method/cache/signal，必须使用当前登录用户权限；禁止管理员Key。
模块权限未确认时不调用setContext；没有可读资源时allowedReads=[]。调用前后均应响应资格变化。

资源与参数：

| resource | 参数 | 提示 |
| --- | --- | --- |
| report | start_date/end_date必填，baidu_account_id可选 | A基础看板：metrics与coverage同时显示；无电话按钮点击指标 |
| keywords | 日期同时给或省略；账户/q/campaign_id/page/page_size | 默认所选账户范围最新报告锚定近7天；电话点击部分覆盖只显示known_subtotal |
| keywordDetail | keyword_id及日期必填，账户可选 | 地域按层级；schedule为星期×小时；需optimize.keywords |
| searchTerms | 账户/q/campaign_id/adgroup_id/page/page_size | 无日期参数；逐条和windows显示实际范围，不跨窗口求和 |

示例传入数字ID，必须是JS安全正整数；若外部ID超出安全整数范围，不能转Number后继续请求，需另评审字符串ID契约。
onClear必须清理工作台SEM视图及派生搜索/对话上下文；本包不控制其他模块、不实现UI缓存。
异步catch遇STALE_RESPONSE可静默丢弃；ACCESS_REVOKED/CONTRACT_MISMATCH需重取资格，不回退数据。
READ_FAILED显示失败，保留范围说明，不补0、不发重同步。服务器仍执行所有客户/模块/身份/菜单校验。

客户端在交给视图前校验已发布的`sem-cockpit-v1`响应：CTR单位必须是ratio；缺报日必须保留
`no_data + null`，不能与真实0混淆；电话`partial`只能提供`known_subtotal`；地域和168个
星期×小时单元在单账户筛选时必须严格同账户，全账户模式保留维度独立观测到的未归属账户；
搜索词逐条窗口必须能对应`windows`且不跨窗口汇总。
筛选回显、账户、日期或这些字段不一致时返回CONTRACT_MISMATCH并清理SEM上下文。
旧请求的迟到响应和迟到401/403先按STALE_RESPONSE丢弃，不能覆盖或清空较新的同资源请求。

`examples.synthetic.json`包含四组真实路由对合成内存数据的响应，外层synthetic=true。
可用于本地mock transport和工作台联调准备，不可当生产结果。响应内is_demo=false是接口形状。

测试：`node --test integrations/sem-cockpit/readonly-client.test.mjs`。测试全部使用本地合成响应，
不建立网络连接。
更多账户/字段/缺失规则见 `../../docs/SEM_COCKPIT_READONLY_DETAILS.md`。

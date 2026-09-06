# SEO 工作台离线消费入口

## 目的与边界

工作台消费现有 SEO 只读接口时，先把同一内容的内容记录、审核字段、分平台发布记录、发布尝试和明确关联的页面详情组装成 `raw`，再调用 `app.seo_workbench_adapter.adapt_seo_workbench_item`。适配器只转换已经读取的数据，不发起采集、生成、发布或数据库写入。

`scripts/render_seo_workbench_example.py` 是可执行的离线示例。它读取纯合成 fixture，调用正式适配器，并输出客户可读 JSON。它不是线上 API，也不是第二套状态适配器。

`frontend/src/utils/seoWorkbenchDisplay.js` 只消费上述适配结果，将发布、页面检查和搜索表现转成三个独立展示区块。它不读取接口、不触发任务，也不根据发布地址、尝试结果或其他指标补出结论。数据未提供时返回 `null`/“—”；只有明确返回的数值 `0` 才展示为零。

```powershell
python scripts/render_seo_workbench_example.py `
  --input tests/fixtures/seo_phase1_workbench.json `
  --output docs/examples/seo_workbench_customer_example.json
```

## 消费顺序

1. 内容列表返回一条内容及其 `tenant_id`、`site_id`、审核字段。
2. 使用同一租户、站点和内容 ID 读取各平台发布记录。
3. 按 publication ID 读取发布尝试；尝试失败和发布记录状态分别保留。
4. 只有消费方已经得到明确、可核对的 URL→页面关联时，才传 `page_binding` 和对应页面详情。
5. 每次请求保存 `tenant_id/site_id/request_id`。响应回来时三者必须仍与当前页面一致，否则丢弃迟到响应。在线调用的 `expected_context` 必须来自独立保存的请求发起上下文，不能从响应正文反推。

离线脚本只处理可信的合成 fixture，因此为了逐场景演示，会从 `raw.content` 构造 expected/response 两侧的同一个 context。这只是合成渲染便利写法，不能照搬成在线身份或作用域校验。

`page_binding` 是消费方已经掌握的显式映射，当前 SEO 没有可供首期使用的自动 URL 映射查询。`source_page_id` 只表示内容或整改任务绑定的来源/承接页，不能证明内容已发布或已经应用到该页。首期没有可靠映射时直接返回 unknown，不新建映射表或推测关系。

JSON 中 `attempts_by_publication` 的对象键天然是字符串；离线入口会把严格正整数字符串归一化为整数 publication ID，并拒绝无效键或归一化后重复的键。

## 客户展示口径

| 场景 | 展示提示 | 禁止推断 |
| --- | --- | --- |
| 审核通过、尚未发布 | 已审核待发布；尚无分平台发布记录 | 审核通过不等于发布成功 |
| 多平台一成一败 | 分平台显示成功 1、失败 1 | 一个平台成功不等于全部发布成功 |
| 发布成功但没有 URL | 没有发布地址，无法检查页面 | 发布状态不能补出 URL |
| 有 URL、没有页面映射 | 尚未关联 SEO 页面记录 | 不能仅按 URL 字符串猜页面 |
| 多个候选页面 | 需要先确认正确页面 | 不能自动选择任一候选页 |
| 只有 `source_page_id` | 这是来源/承接页，不是发布页证据 | 不能用来源页检查验收发布页 |
| 来源页最新检查失败、历史成功 | 仍不作为发布页检查；显式映射后也只使用最新检查 | 不能用历史成功覆盖最新失败 |
| 历史自审 | 历史审核，独立性未确认 | 不能宣称独立审核 |

审核、发布、页面检查始终是三个状态。页面 `assessment_state=assessed` 只证明检查执行完成；当前接口没有全页面“通过”字段，因此 `passed=null` 表示未知。搜索效果中的 `article_clicks=null` 也表示未知，不能把业务总点击、关键词点击或同一主题点击分摊给某篇文章。

`reviewed_at` 只有在字段为 API 输出的 ISO 日期时间时才能支持“审核通过”；空值、无效日期或只有日期都按未审核展示。明确关联页面有最新快照时，快照的 `url` 或 `final_url` 必须与关联页面地址一致；不一致的快照不能作为该页面的检查证据。

## 仍需协调的输入

- **工作台开发**：在实际请求层维护 request ID，组装 `attempts_by_publication`，并只在已有可靠关联时传 `page_binding`。
- **服务器联调**：专用只读身份落实后，核验 tenant/site 归属及字段形状；不得使用管理员密钥。
- **真人验收**：首期只读登录权限和页面文案可理解性需要真人确认。离线样例不代表线上功能已经接入。

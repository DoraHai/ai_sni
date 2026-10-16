# 多号通离线交接格式 v1

日期：2026-10-16。适用：SEO 生成文件 → 操作员在单独安装的多号通中人工发布 → 操作员填写文件 → SEO 导入人工回执。文件是人员之间的离线约定，不是多号通原生导入协议，也不接入 `/api/distribution` 或桌面自动化协议。

## 编码与文件结构

- 所有文本为 UTF-8。导出无 BOM；回执导入兼容 UTF-8 BOM。
- JSON 顶层为对象数组，字段名区分大小写。CSV 为 RFC 4180 风格，首行表头、逗号分隔、CRLF 换行；引号、逗号及正文内换行用双引号包围，内部双引号写成两个双引号。
- JSON 的空值使用 `null`，CSV 使用空单元格；ID 始终作为文本处理，避免 Excel 截断长整数。
- “导出发布单”返回 `seo-offline-orders.zip`，内含 `orders.json`、`orders.csv`、`receipts-template.json`、`receipts-template.csv`。同一批发布单的 JSON/CSV 为两种表示，选择其中一种使用，不重复派单。
- 每次导出最多20篇，发布单 JSON 内容最多2MiB。每次回执导入最多200条，上传文件最多2MiB；只接受 `.json`、`.csv`。一行对应一篇稿件、一个平台、一个账号。
- 文件只包含本次人工交接所需信息；账号是操作员可识别的非敏感备注，不填写登录密码、Cookie、密钥或授权信息。本机验证只用合成数据，禁止下载生产稿件或回执到工作机。

## 发布单

CSV 表头顺序固定：

```csv
article_id,title,content_markdown,material_path,target_platform,target_account,scheduled_at,source_version,payload_hash
```

| 中文字段 | 键 | JSON 类型 | 规则 |
|---|---|---|---|
| 稿件ID | `article_id` | string | 正整数十进制字符串，无前导零，范围1至9223372036854775807；对应 SEO 内容资产ID |
| 标题 | `title` | string | 非空，来自已审核稿件 |
| 正文 Markdown | `content_markdown` | string 或 null | 与素材路径至少填写一项；保留换行。支持 Markdown 中内嵌的经过 SEO 清洗的 HTML 块；编辑器富文本以此形式保留段落、表格与图片引用，不做有损纯文本转换 |
| 素材路径 | `material_path` | string 或 null | 相对交接包的文件路径，例如 `materials/10/article.md`；不得为绝对路径或包含 `..`；引用文件必须随包交付。当前最小导出使用内联正文，此字段为 null，不读取操作员本地文件 |
| 目标平台 | `target_platform` | string | 下表25个完整渠道名之一，区分大小写，不用简称或 SEO 旧渠道编码 |
| 目标账号 | `target_account` | string | 1至120字符的非敏感账号备注；操作员人工对照多号通账号；无首尾空格、控制字符及 `= + - @` 起始公式前缀 |
| 排期 | `scheduled_at` | string 或 null | 带时区 ISO 8601，例如 `2026-10-20T09:30:00+08:00`；null 表示待人工安排，只是提示，不创建定时任务 |
| 原稿版本 | `source_version` | integer | 正整数；CSV 为十进制数字；必须原样保留至回执 |
| 原稿内容摘要 | `payload_hash` | string | SEO 提供的64位小写十六进制 SHA-256，绑定客户可见的业务字段；必须原样保留至回执，不能仅对导出正文重新计算 |

后两个字段是防止旧稿误回填的必需前置条件。导出会重新验证租户、站点、SEO 内容编辑权限、内部审核和当前版本的客户/顾问确认（沿用生产分支现有确认门禁及兼容逻辑）。文件中正文不等同于渠道专属稿；视频、图集等渠道需要操作员另外备齐对应素材，目录存在不代表具备发布能力。

JSON 示例（全部为合成数据；摘要仅展示格式，不能直接用于真实导入）：

```json
[
  {
    "article_id": "10",
    "title": "合成测试稿",
    "content_markdown": "## 操作说明\n\n这是一篇合成测试稿。",
    "material_path": null,
    "target_platform": "微信公众号",
    "target_account": "合成账号A",
    "scheduled_at": "2026-10-20T09:30:00+08:00",
    "source_version": 3,
    "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
]
```

CSV 示例：

```csv
article_id,title,content_markdown,material_path,target_platform,target_account,scheduled_at,source_version,payload_hash
10,合成测试稿,"## 操作说明

这是一篇合成测试稿。",,微信公众号,合成账号A,2026-10-20T09:30:00+08:00,3,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

CSV 防公式规则：导出时，自由文本去掉前导空白后若以 `= + - @` 开头，单元格前添加一个 ASCII 单引号。JSON 保留原文；遇到这类标题/正文，人工填稿以 JSON 原文为准，勿把保护单引号当作正文。生成的回执模板自身可直接往返导入。

## 回执

CSV 表头顺序固定，JSON 仅接受以下字段（未知字段拒绝）：

```csv
article_id,platform,account,public_url,published_at,status,source_version,payload_hash
```

| 中文字段 | 键 | JSON 类型 | 规则 |
|---|---|---|---|
| 稿件ID | `article_id` | string | 与发布单一致 |
| 平台 | `platform` | string | 同一25渠道枚举；应与实际人工发布的平台一致 |
| 账号 | `account` | string | 1至120字符，沿用目标账号备注；无首尾空格、控制字符和公式前缀 |
| 公开链接 | `public_url` | string 或 null | published 必填；完整 HTTPS URL，含主机名、合法端口，不含用户名/密码、空白、控制字符或反斜线；failed/unknown 必须为空 |
| 发布时间 | `published_at` | string 或 null | published 必填；带时区 ISO 8601，精确到秒，可带1至6位小数；failed/unknown 必须为空 |
| 状态 | `status` | string | 只能为 `published`、`failed`、`unknown`，区分大小写 |
| 原稿版本 | `source_version` | integer | 与原发布单一致，不接受 JSON 字符串或布尔值 |
| 原稿内容摘要 | `payload_hash` | string | 与原发布单一致，64位小写十六进制 |

`published` 表示操作员确认完成发布并提供可公开访问的链接，导入时仅校验格式与范围，不自动访问外部链接，不等同于平台核验、正文匹配、外链成立或搜索收录。`failed` 表示人工确认失败，`unknown` 表示结果待核对；两者都不能计为发布成功，也不会自动重试发布。

JSON 示例：

```json
[
  {
    "article_id": "10",
    "platform": "微信公众号",
    "account": "合成账号A",
    "public_url": "https://example.invalid/articles/10",
    "published_at": "2026-10-20T09:35:00+08:00",
    "status": "published",
    "source_version": 3,
    "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  {
    "article_id": "11",
    "platform": "搜狐号",
    "account": "合成账号B",
    "public_url": null,
    "published_at": null,
    "status": "unknown",
    "source_version": 1,
    "payload_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
]
```

CSV 示例：

```csv
article_id,platform,account,public_url,published_at,status,source_version,payload_hash
10,微信公众号,合成账号A,https://example.invalid/articles/10,2026-10-20T09:35:00+08:00,published,3,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
11,搜狐号,合成账号B,,,unknown,1,bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
```

## 25渠道枚举与来源

来源是本机多号通仓库 `D:\微信小工具箱项目\wechat-toolbox-real-execution-desk-20261014` 的固定提交 `e3c9d0b`，读取 `src/shared/accounts.ts` 的 `PLATFORM_IDS`、`PLATFORMS` 和 `src/shared/supplemental-platforms.ts` 的 `SUPPLEMENTAL_PLATFORM_ENTRIES`。使用源码完整 `name`，不是 `shortName`。仅只读查阅，没有修改或启动该工作区。

| 多号通渠道ID（仅供对照） | 发布单/回执使用的完整渠道名 |
|---|---|
| wechat-official | 微信公众号 |
| wechat-channels | 微信视频号 |
| xiaohongshu | 小红书创作服务平台 |
| zhihu | 知乎创作中心 |
| bilibili | 哔哩哔哩创作中心 |
| douyin | 抖音创作者中心 |
| weibo | 新浪微博 |
| linkedin | LinkedIn 领英 |
| toutiao | 今日头条创作中心 |
| baijiahao | 百家号创作中心 |
| kuaishou | 快手创作者服务平台 |
| sohu | 搜狐号 |
| netease | 网易号 |
| penguin | 企鹅号 |
| yidian | 一点号 |
| dayu | 大鱼号 |
| jianshu | 简书 |
| csdn | CSDN |
| juejin | 掘金 |
| cnblogs | 博客园 |
| segmentfault | SegmentFault（思否） |
| oschina | 开源中国 |
| smzdm | 什么值得买 |
| tieba | 百度贴吧 |
| xueqiu | 雪球 |

## 导入校验、幂等与存储

1. 先选择客户与 SEO 网站，再上传文件。预检通过前不能确认导入；提交时重新校验整批。租户、站点、稿件归属、内部审核、现有客户确认门禁、版本与摘要都必须通过。
2. 同一文件内 `(article_id, platform, account)` 不得重复；同一稿件的公开链接也不能在文件内重复。任一条格式、版本、归属或链接冲突，整批不写入。
3. 幂等键由协议版本、租户、站点、稿件ID、平台、账号、原稿版本和摘要组成。相同内容重复导入不新增发布记录或操作记录。unknown/failed 可人工补回 published；已有 published 不允许覆盖链接、修改时间或降级。不同账号不能认领同一稿件已登记的同一公开链接。
4. 复用 `seo_content_publications` 存放三种人工回执状态，`publish_mode`/`platform_code` 均为 `manual`。账号备注、版本、摘要、人工来源保存到现有 `seo_publish_attempts.request_summary`，可在原发布记录的操作记录中追溯。
5. 只有 published 更新内容资产的发布状态与首次公开链接；failed/unknown 保留为人工回执，既不提升主稿状态，也不调用发布平台。时间导入后统一转换为 UTC，再沿用现有 UTC 无时区字段存储。
6. 未持久化发布单或排期，也不会根据账号备注自动选择或操作账号。因此操作员仍须人工核对实际账号、渠道素材要求、排期和公开页面，再填写回执；文件本身不构成发布证明。

# SEM 同行与产品范围分离（PR #250 已合并，未发布）

本文记录 PR #250 时的契约与历史回放。合并后五词验收及后续调整见
`SEM_EXPANSION_VERDICT_BOUNDARIES.md`，不要将下方旧回放数量当作当前结果。

## 真实问题与来源

2bcdda409060f6533664ae42e477f0fe9cd1ca93 合并版本的五词 qwen-plus 隔离请求，
于 2026-09-03T13:48:45.127359+00:00 发起，HTTP 200、12.58 秒完成，5 项均无报价。
其中“艾仕得水性漆”返回 relevant/watch，basis.relation=peer、intent=information，
引用仅为客户原文中“艾仕得、阿克苏诺贝尔是同行竞品，不是自有品牌。”。
reason 却是“水性漆是否属同业务待确认”：品牌同行关系被当成具体产品范围依据。

完整原始 model_output 和来源哈希保存于 tests/fixtures/sem_expansion_peer_observed_20260903.json，
从本地授权调用记录无损复制；不补造 subject/product_scope，不改变旧输出、画像或评分草案。

## 契约调整

仅对 basis.relation=peer 增加两层结构，既有同行引用仍须属于当前客户的白名单字段：

| subject | 必需内容 | 应用处理 |
| --- | --- | --- |
| entity | information/navigation 意图，product_scope=null | 按原有 relevant/watch 或 relevant/drop 契约；导航只能 drop，peer 永不 adopt |
| offering | product_scope.relation=in_scope，另有合法 field/quote | 继续原有一致性和价格校验；peer 永不 adopt |
| offering | product_scope 缺失、unknown、out_of_scope、非法字段或非客户原文引用 | generic/watch、固定待确认理由，清空两项 AI 报价 |
| 缺失/非法 subject，或 entity 带矛盾的 product_scope | 不推断、不按理由关键词补造结构 | generic/watch，清空 AI 报价 |

主体信息指公司/品牌本身或官网导航；涉及具体产品、服务、技术品类、替代和选型时须为 offering，
不能因 intent=information 就视为 entity。同行名单不能替代产品范围依据；范围未知优先进入人工复核。
product_scope 字段白名单与原有引用一致（industry/business_desc 及明确的中文别名），不允许任意属性读取。
没有新增客户特例、品牌字典、从自由文本 reason 猜业务范围的规则或第二次模型判定。

## 这不是语义正确性的证明

新增字段仍由模型生成，所谓“另给范围依据”是结构分离，不是独立第三方事实认证。
模型仍可能把产品错报成 entity，或声明 in_scope 并引用真实但不支持该产品的文字；
当前代码无法证明引用与候选词的语义蕴含关系。测试保留这两个仍可通过的反例，避免虚报问题已全部修复。
也不声称修复模型把同行误报为 in_scope 的情况。不得因此开启自动采纳或真实写回。

本轮能保证的是：按新结构明确声明产品范围未知、范围外、缺失或非法时，不放行相关结论或 AI 报价。
模型是否忠实选择 subject、完整生成范围依据及其耗时，必须之后单独授权调用验证，未在本轮测得。

## 历史回放与代价

- 五词历史原始标签仍符合 4/4 评分草案（第 5 条边界词不计分但仍需检查）。
  新代码回放保留 1 条采购词，4 条待确认；草案符合变成 1/4，不把此数字说成新模型准确率。
  其中 3 条 peer 缺少新结构（包含本来正确的竞品替代和公司信息），猫粮仍因依据与标签冲突待确认。
- 更早的 20 词原文仍保留不变；因 7 条同行返回缺新结构，新回放为 7 条保留、13 条待确认，
  草案符合为 7/17。没有把旧 peer 结果偷偷补充“已知范围”来维持漂亮的通过率。
- 因此新增结构会提高旧格式返回的人工复核量；语义覆盖、返回长度与成本需审核，不是免费提升准确性。

## 范围与验证

从最新 main 2bcdda4 创建 codex/sem-expansion-peer-scope，仅修改 SEM 评估器、测试/样本及说明。
无前端、共享 AI 客户端、app/baidu、SEO/GEO/门户/诊断中心、服务器或 Nginx 变更。
不新增 Schema，不执行 Alembic，不修改生产数据；migration=not-run。

本地 12 个相关 Python 测试文件合计 343 passed，1 个既存 jieba/pkg_resources 弃用警告。
测试覆盖真实原文回放、当前客户引用、中文别名、非法范围结构、entity/offering 冲突、范围未知时清价、
不自动采纳、人工价格/候选状态/客户资料不变，以及原有超时、5 词上限、去重、隔离等回归。
所有测试使用 mock，不调用模型、百度或生产数据库。原始记录与本地授权调用记录完整一致。

提示词改变会改变评估指纹，未来发布后旧缓存标为 stale；不会自动重评或回填。保存的旧缓存不因
此次本地回放而改变。新的待确认结果仍按既有规则缓存，重评必须人工明确发起。
本轮不提交发布。若后续通过审核，仅按 SEM 后端独立发布流程同步，不能整份部署 main。

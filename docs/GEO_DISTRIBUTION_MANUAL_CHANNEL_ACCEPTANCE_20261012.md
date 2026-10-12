# GEO 微信渠道人工定版：本地验收交接

运行代码冻结：`9c573ee91089cd1d77773e39a4600bf90ca151bb`；tree `44080a7be1307316a0f4f4dcff0646d6e3ae30a8`。基线 `ba713f06da330362cd0539531e4edd3216a09d78` 保持原树只读、干净。新树 `D:/SNIPERS国内版/ai_sni-worktrees/geo-manual-channel-acceptance-20261012`，分支 `codex/geo-manual-channel-acceptance-20261012`。

仅改 GEO 内容路由/schema、人工定版 helper、来源 adapter、编辑器/API 和必要测试；中央、多号通、共享 main/鉴权、SEO、SEM、生产数据库均未修改。不新增生产 DDL，不部署、不推送、不调用付费 AI、不发表文章。

## 行为与门禁

此前存储稿 `publishable=false / adapted_draft_not_publishable / html_preview_only`，即使母稿批准也只是预览稿。现在顾问可明确人工核对定版，服务端重新执行当前母稿和渠道稿的 full_article_v2、品牌、事实/规则、逐句证据及 lint。通过后克隆新渠道版本，记录 manual 来源、操作者/时间、五项确认、UUID、正文/HTML/母稿/事实/素材摘要，旧预览稿和历史正文保留。旧客户批准作废，当前状态重新 pending。定版不授予批准、不创建 GeoPublication。

只开放 `wechat`，仍按原纯文章素材契约，不依赖可选 GeoChannelAsset 表；其他渠道 422。图片标记和 HTML 纳入正文版本摘要；本批不代表图片文件或平台渲染已自动核验。再次改稿会保存预览后继版本；改母稿、改事实、改 HTML/图片标记、撤审/退回、当前顾问撤权都阻断旧定版。退回后单独再批准不复活定版。批准还绑定本次客户 reviewed_by/reviewed_at，编辑器用服务端 `manual_finalization_current` 显示效力。

已保存的渠道稿可在显式定版时关联当前最新母稿：GET 提示 `requires_master_rebase=true`；POST 必须核对当前母稿 ID、渠道 ID 和实时上下文 digest，母稿/渠道均通过真实检查后才克隆并关联，历史记录保留 source_article_id。旧 source 的 latest/stale/审核/客户范围门禁不放宽。

## 精确原生 API

使用当前登录 JWT。tenant/scope/project/业务/prompt/task 归属和当前顾问权限每次重查。不得客户端自报 publishable、审核标记、定版 metadata 或直接 DB 翻标志。

1. 必要事实核查：`POST /api/v1/geo/facts/{id}/verify?tenant_id={tenant}`。本轮原生 fact4/fact6 请求的 excerpt/locator/source_url/note/verified_translation/expected_source_statement/name/url/public_use_allowed 见下方私有 recipe；这些是本地核查，不修改生产 facts。
2. 原样稿未过时明确手工保存新母稿：`PUT /api/v1/geo/content-tasks/{task}/article?tenant_id={tenant}`，body `{expected_article_id,title,body_markdown,outline:{}}`；再保存渠道预览：`PATCH /api/v1/geo/content-tasks/{task}/variants/wechat?tenant_id={tenant}`，body `{title,body_markdown}`。原母稿/预览保留。
3. 顾问 `GET /api/v1/geo/content-tasks/{task}/variants/wechat/manual-finalization?tenant_id={tenant}&scope_id={project}`，取得 `variant_id/article_id/revision/export_revision/requires_master_rebase/quality_passed/issues`，核对保存版本。
4. 同 URL POST 严格请求如下。ID 取自身 GET 的正整数；revision 为当前 64 位小写 SHA256；每个新意图生成新 UUID。五项必须是布尔 true，数字 1/缺确认/额外 publishable 等字段 422。

```json
{
  "scope_id": 9001,
  "expected_variant_id": 4,
  "expected_article_id": 18,
  "expected_revision": "<当前 GET 的64位revision>",
  "request_id": "<新UUID>",
  "confirm_title_body": true,
  "confirm_layout": true,
  "confirm_facts": true,
  "confirm_brand_author": true,
  "confirm_platform": true
}
```

示例编号属于隔离环境。revision 服务端计算：`digest([export_revision(variant,current_article.id),master_digest(article),digest(current_fact_dicts),asset_digest(actual_channel_assets)])`。digest 为 JSON sorted keys、ensure_ascii=false、紧凑分隔符、default=str 的 UTF8 SHA256；export_revision 沿用原 export_view 算法。使用 GET 值即可，不复用测试摘要。

POST 返回最新 task 和 `manual_finalize_result={variant_id,source:'manual',idempotent,review_required,publishing_authorized:false}`。同 UUID 首次并发只创建一个定版，另一请求幂等；不同 UUID 竞争同旧快照，后者 `geo_manual_version_stale` 409。合法重放不重置已完成客户审核，失效重放 409。

5. 该客户实名账号重新读 `GET /api/v1/geo/content-tasks/{task}?tenant_id={tenant}`，再 `POST /api/v1/geo/content-tasks/{task}/review?tenant_id={tenant}`：`{decision:'approved',expected_article_id:<当前article.id>,expected_updated_at:<当前task.updated_at>,note:<该次真实确认>}`。pending 时顾问自行批准 403。客户确认是真实交付前的人工步骤。批准后 intake 可 ready，source_revision 必须等于实时 load_source；批准前 source 409。ready 不能替代中央后续逐稿授权及项目/账号/渠道门禁。

## 前端入口

GeoTaskEditorView 公众号标签的文稿说明区域新增“人工核对并定版”：先保存母稿/渠道稿，选择当前项目，读真实检查，核对标题正文、排版/内嵌配图、事实及跨语言对应、品牌署名、公众号要求五项，再提交。显示当前母稿关联与客户重审提示。客户 view 账号无该按钮且后端拒绝定版。HTTP 期间继续输入时保留本地未保存稿，不用晚到响应覆盖输入。

## 原样稿、分类与人工修订边界

完整私有快照 SHA256 `f75d382a54ec33f0c892cc4c6afcc17b082c130cc1b58236fb4dde48e383f609`。原 tenant1/business13/task12/article17/v4/wechat2 全文不在 Git。原样稿仍 409，单客户批准原样预览也不能 source ready。

67 项人工初分：结构/方法问句4，资料准备与核对29，来源/署名4，资料表格4，泛化/因果/边界 FAQ20，品牌/产品断言6。初分不是放行标记。最终保守语法只自动豁免原67中的方法问句1、结构导览3；其余63继续要求顾问核事实或规范纯流程表达，不能说63全是虚假事实。

新分类完整匹配“有限动作＋纯资料对象＋可选固定接收方”；未知尾部、英语适用性、技术状态、数据、因果、比较不能匹配。方法问题也限制纯领域对象；表格每格须固定资料标签或同样受限指令。旧步骤宽尾部和任意“选择...”指导豁免收紧。数字/单位/性能/适用性/案例/跨语言 claim_guard 与逐字事实对应仍执行，无客户 nonclaim/ignore 开关。

实际负例“建议确认产品消除振动。”“请核对设备运行更安静。”“建议确认MAXXDRIVE XT is compatible with conveyor systems.”“建议检查该公司来自德国。”“请核对产品获得欧洲专利。”均要求证据；邻近“请核对设备资料。”可豁免。

正向另存为**基于客户原主题/清单字段的本地人工修订新版本**：删未对应断言和模糊因果，仅保留纯资料动作、原 fact4/5/6 英文原句和严格 fact4 中文译文。没有声称原稿未改自动合格。修订稿用于流程验收，不是实际客户批准/对外成品。

fact6 当前官方 XT 页短句“it is well suited for belt conveyor systems.”（9词），通过原生 verify 记录 `MAXXDRIVE XT适用于带式输送系统`，定位 Built for Bulk Material Conveyor Applications；fact4 当前官方首段“engineered for continuous operation in demanding environments”（8词），记录 `诺德 NORD DRIVESYSTEMS 的 MAXXDRIVE 工业齿轮箱为苛刻环境下的连续运行而设计。`。保留来源 URL、短 quote、locator、expected source 字段、当前本地 test actor。证据为主窗口已读取的 fact4-current.txt/fact6-current.txt。未增降噪/寿命/项目性能承诺，系列扭矩不当作单型号承诺。

## 测试与产物

108 项 Python 通过：真实 PG/JWT20＋追加首次冷并发2；单测86（新严格分类45，旧审核权限16，旧改稿审核9，逐句证据10，claim_guard6）。真实场景没有 mock 认证/归属/规则/事实/审核/来源 writer，仅 DB 依赖定位隔离 schema；旧纯权限单测的既有 stub 与真实证据分开。前端审核/文章版本/编辑竞态22通过，生产构建通过（既有 chunk size/PURE 注释警告）。未测真实平台或真实浏览器。

产物均在 `C:/Users/Administrator/AppData/Local/Temp/`，全文只在私有 TEMP：

|文件|结果|SHA256|
|---|---|---|
|geo-manual-native-final-20261012.xml|20 passed, 0 skipped|ec06c5f97191770d884d4f1a6ba595b66e16f8fda9b2f6e8f06798861c6b9364|
|geo-manual-cold-concurrency-20261012.xml|2 passed, 20 deselected|8b42ae62297f9bf826c88646197ec51a3aa2ba1ccb35892457ba9d1983fbcaf0|
|geo-manual-unit-final-20261012.xml|86 passed, 0 skipped|d7bb89b35203c90793404c4a92cd502c72d1dc0f5e523a27d091e0c2256b15ad|
|geo-manual-frontend-contracts-20261012.log|22 passed|ca285c403fc501744479ce951ef8b428b46316b988fd77031b77c8644db36ea4|
|geo-manual-build-final-20261012.log|Vite passed|380dbb1c1f6a222260d8413de20256bd55d21511e493a3cce4665555d312f421|
|geo-manual-revision-final-20261012.md|1539 chars, private LOCAL revision|65de75d0991fc67e81dc812b9c210cf28705fd49a271f941b07af49f12b3664c|
|geo-manual-api-evidence-recipe-20261012.json|private verify requests/body-file recipe, no JWT|25027554989014f0373e9284323c601a432f702cb8b1b068d8630d818819d77d|

构建 `geo-manual-acceptance-build-final-20261012/assets/GeoTaskEditorView-int_JgGU.js` SHA256 `ab55039a5cb99f075648236f09bfc1ad747626e155ff2efe7d0bc70d3f96bc1a`，未部署。

raw SHA256：分类器 `0358506170751cb8b95531dc8760de4baa0640a89b742ceeb506cc93259d6991`；人工定版 helper `27b96f1af6c700371728c3d2dc846e2313b30182e2bd68a7ec0f5511a94e18bc`；来源 adapter `122425f8c1a4289ceaa31b45c734e4bcc469ade1cc535d01dd91eb56ee6c09e0`。分类器 Git blob `2e5b3d4b1900e61bf3035e20dcb556ea449fa2aa`；Git 行尾规范化与 raw 字节区分。

仅使用自有 PG16.15 `127.0.0.1:55527/geo_manual_ci`，随机 geo_manual_test_<uuid> schema，最终 schema 数0。自有55527已停止、无监听；未使用/停止中央55463、旧55443或其他共享服务。该自有库仅留下空 demo registry。前端 ignored 的临时依赖 junction 删除被自动策略拒绝，保留它；没有改其指向的原项目代码。tracked 工作区干净。

中央下一步消费此精确 GEO freeze，在独立环境执行实际 native HTTP→中央→多号通整链，独立 reviewer 复核分类边界。本批原生成功不声称该完整整链已完成或文章已实际发布。

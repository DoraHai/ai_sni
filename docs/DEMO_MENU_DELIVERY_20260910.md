# 演示菜单交付记录 · 2026-09-10

## 目标与范围

用户要求演示账号能看到 SEM、SEO 主要菜单，并有可查看的演示数据与明细。
同域入口 `/workspace/cockpit`；账号 `workbench_test_readonly`，user_id=5，tenant_id=16，role_id=4。
密码、令牌、管理密钥不记录在本文档。

菜单权限可见、页面读取成功、演示数据存在、操作可模拟是四个不同验收项。
不得仅根据授权成功或 HTTP 200 声称全部功能演示完成。

## 平台已执行

通过正式 `/api/v1/roles/4` 管理 API 更新权限，未直接修改数据库表。
更新前 `/users` 校验 role4 仅绑定 user5，客户为16，角色非系统角色。
原六项 view 保留：seo.site、seo.content、geo.content、monitor.dashboard、optimize.keywords、optimize.searchterms。
新增六项 view：seo.assets、seo.dashboard、seo.alerts、seo.keywords、seo.links、seo.competitors。
更新后共12项 view；未授平台管理或 edit 权限。

以普通演示账号登录后验证 `/auth/me` 返回上述12项权限。
SEO `/overview?tenant_id=16&engine=baidu` 返回200及 demo_meta；
`/keywords?tenant_id=16&engine=baidu&page=1&page_size=20` 返回200、4条演示关键词；
`/content-assets?tenant_id=16` 返回4条；`/workbench/sites?tenant_id=16` 返回演示网站1601。
源版本为 tiger_seo_full_domain / 2026.09.10-v1；页面检查为公开网页预采集，内容、发布、排名为演示。

## 各模块边界与待交付

- 工作台统筹：平台菜单授权、普通身份验收、汇总上线状态；不替模块重写业务接口。
- SEM窗口：生产984c5bec的嵌入样例目前接在 cockpit 接口，模块页面仍需适配；先给最小权限建议，再补页面→接口演示映射与必要测试/PR。禁止真实百度调用与回写。
- SEO窗口：生产8e1ebc97已有网站、看板、趋势、关键词、内容、页面诊断及分发核心读取；优先补 alerts、links、competitors。QA与视频作为后续独立范围，不阻塞首批菜单。禁止真实生成、采集、发布。
- GEO窗口：生产82e07fd1独立前端各页使用 geo.content；保留该view即可，不增加geo.assets/geo.diagnosis。通过integration/read补只读演示页面覆盖，旧业务GET保持拦截。

数据库建表、迁移或合成数据落库仍由用户协调数据库负责人。本轮权限使用已有管理API，不需要迁移。
代码提交、合并、实际部署、普通账号页面验收分别记录，开发开始不等于已上线。

## 待补发布记录

SEM/SEO/GEO本轮代码PR、部署SHA与逐页面验收结果：待各窗口回传。

## 17:25 推进记录（Asia/Shanghai）

- SEO #525 / 7f4ae0f3：已审查三文件差异与权限/隔离测试。专项39通过、回归697通过/107跳过，开发反馈CI全绿。已授权SEO窗口核验准确HEAD后按原流程合并部署；实际部署及普通账号验收待回传。
- SEM #526 / c5d06b29：已有三页演示适配，94 Python和2前端测试通过；目标main，仍需分别准备生产前后端推广。要求检查关键词刷新GET路径与客户可读提示文案，待新SHA。
- GEO #527 / 684a774d：82项focused tests通过，但方案把所有演示入口收缩成一个总览，与用户“菜单丰富”目标不符，暂不批准合并。已要求至少总览、问题监测、回答与引用、内容任务四个可切换演示入口，均保持geo.content:view和integration/read。
- 三开发窗口均已收到推进要求；12项只读角色权限不变。本轮额度剩余13%，未触发5%暂停线。

## 17:33 上线核验（Asia/Shanghai）

SEO实际current已为20260910T092707Z-d77143dc485f。以普通演示身份验证alerts、competitors、internal-links、backlinks全部HTTP200且demo_meta.demo=true，分别4条异常、2个竞品、26个内链节点、3条外链。这是接口与实际部署核验，尚不等同浏览器逐交互全验收。SEM第一批提交已更新985653dc，第二批代码正在修改；GEO四入口方案正在修改，未重新批准部署。

## 17:49 发布衔接（Asia/Shanghai）

- SEM 第一批985653dc已修正文案及刷新保护；生产推广后端#529（9c5eb33e）、前端#530（00cc0e81）。已授权开发核对推广差异和准确HEAD检查后，按main→后端部署核验→前端部署核验顺序推进。尚未收到实际部署结果。第二批#528/a033516b覆盖计划、单元、预算、预警、调整记录，暂未批准生产推广或新增权限。
- GEO #527/fa3b3ed已核对为相对最新生产仅6个前端文件，四入口及回答/任务详情方向通过。要求补请求序号防快速切页旧响应覆盖，并校正模块标题；准确HEAD测试/CI通过后已授权既有流程部署，实际部署待回传。
- SEO 本批已归档关闭；API普通身份验收完成，浏览器逐交互仍未验。QA/video不自动扩大范围。
- 本轮快照SEM/GEO均正在执行发布衔接，SEO已完成；无新增人工或数据库需求。角色仍12项view。最近额度剩余12%，未到5%暂停线。

## 17:59 GEO 上线后普通身份核验

开发回传#527部署b984d8a5ff78fe5e114963fde32608a200174f6a（run34462730234），健康及静态资源通过。统筹用普通演示账号正式登录，独立读取integration/read：summary、questions（12）、content-tasks（2）、answers（limit50返回50，未加完整周captured窗口，不作为本周总数）、首条回答详情与首条任务详情均成功；任务含2个版本、3个渠道稿。仅API核验，浏览器菜单/快速切页交互仍未验。未调用业务写接口，凭证未记录。

## 18:13 SEM 首批上线与第二批边界

- #526 main=45ba7556；后端#529实际生产b9e3c7805662453188ba7c65a4351328e5ee835c，run34463052231成功；前端#530生产3ed5c2e9b6948272f54e53a5f0b6b01412dfb831，run34463526409成功（开发回传）。
- 统筹普通账号登录，带tenant_id=16验证dashboard/today、keywords、search-terms均200，关键词6条、搜索词6条，响应含演示元数据；省略必需tenant_id会422，非登录失败。浏览器逐交互仍未验。
- #528第二批a408d805相对main12文件已初审。要求去掉isinstance(ctx,AuthContext)导致无有效ctx仍落真实查询的兼容路径，直接单测传有效身份；准备生产推广草稿PR待最终核对，未授权第二批上线或扩权。
- 额度剩余11%，未达到5%暂停线。无新增人工或数据库需求。

## 本批收尾（用户要求暂不继续验证）

- SEM第二批修正039f9ac5已通过审查及CI。开发回传#528 main=7d6ef50c；#531后端生产7fe82ebec419454b80fe22b22cf3e8c6b1d22012（run34465719699成功）；#532前端生产37cf821980282f3c9369fa6bee7b1201d0fddf46（run34465893572成功），健康及五个页面静态资源核验通过，无迁移或业务执行。
- 统筹通过现有角色API再次确认role4仅user5/tenant16、非系统角色，新增manage.campaigns/manage.adgroups/manage.account/monitor.alerts/verify.adjustments五项view，API读取确认共17项view。无平台管理或edit权限。
- 用户明确“不要验证，先补”，因此未继续第二批普通身份读取及全模块浏览器逐页验收，不声称全交互通过。
- 本轮约定菜单与数据代码已部署、权限已补；SEO QA/video与模拟执行全过程属于后续独立范围，不自动扩展。结束本轮自动监测。

## 20:57 演示首页数据与排列修复

- 用户截图暴露三个实际问题：SEO页面响应不符工作台读取契约；GEO演示账号首页仍读取正式指标，因模拟样本被正确排除而显示不可用/0；线上指标区丢失原型分组并出现内层滚动，无数据依据的固定演示事件与真实状态冲突。
- SEO #534已部署 dcd989c71c5bba20d38020fd410e34e2ca36f2f8（run34479343695），无迁移。普通演示身份的线上响应经现有 createSeoAuthorizedClient/read-only client 重放，contents=4、pages=26，均通过。
- 工作台 PR #533已部署 production-sem=54dfdc542caa368541a15bfdb56a43aa2391a7d5（run34479743912）。精确演示身份先走GEO正式资格预检，再读取demo-summary/capabilities；显示50%提及率、18次提及、12次官网引用、36条回答、3个演示覆盖引擎，全部标记不进入正式指标。恢复“趋势与投入/内容与品牌”分组，去掉指标区限高内滚动和固定伪事件，无真实事件时不留空事件面板。
- 验证：PR #533 pytest、sem-frontend-build、生产发布全部成功；线上入口引用 AcquisitionCockpitView-cxfU9G0a.js，包含新分组与GEO演示消费，不再包含“正在播放演示事件”。未代用户完成浏览器视觉验收。

## 21:45 老虎演示身份与三模块内容统一

- 通过现有客户管理 API 将专用租户16的显示名改为 `TIGER 老虎新材料（演示）`；账号、租户ID、权限及模块开通状态未变。
- 工作台 PR #535 已部署 production-sem=`58b2829b7872b35b5cff7e48ddcd6512a73f4a40`（run34482310666）。演示身份下智能区明确显示“AI 演示助手 / 交互演示台 / 演示模式”，并说明回答和屏幕联动仅用于产品体验；真实客户模式仍保留 DeepSeek 指令能力文案。
- SEM PR #536 已部署 production-sem-backend=`6674930beb1a9915de2b875a4da962d0b56ecca8`（run34482880274）。演示关键词、搜索词、账户、计划、预警与调整记录统一为 TIGER 粉末涂料及表面技术场景；演示ID、指标和只读边界未变。
- GEO PR #537 已部署 production-geo=`2aff472b39ab02c70a903d06547d311310960fc0`（run34483721529）。12个问题、72条回答、事实卡、任务及渠道稿统一为 TIGER 粉末涂料场景；全部继续标记 synthetic/never_official，正式指标仍不采纳这些样本。
- 普通演示身份线上核验：SEM关键词与搜索词、GEO demo-summary 均HTTP 200，均命中 TIGER/老虎内容且不再出现旧设备运维/G-Snipers Demo主题。线上驾驶舱资源包含新的演示助手文案；浏览器视觉仍需用户刷新后查看。

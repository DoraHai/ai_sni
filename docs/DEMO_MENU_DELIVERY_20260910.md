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

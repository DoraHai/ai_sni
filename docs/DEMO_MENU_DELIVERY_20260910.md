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

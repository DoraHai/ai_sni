# 普通客户切换也要失效旧页面和请求

前端基线：`9896c2ba00b4fd221eb632c7daef5d2f4ada068b`。

普通多客户用户的 setTenant 原先只改 tenantId，不更新 authRevision。
实际画像页的 tenant watch 在重新加载失败时保留旧 data；Axios 也会接纳旧客户的延迟响应。
因此即使后端已返回身份冲突 409，页面仍可能显示上个客户的业务资料。
顾问切客已有鉴权版本通知；本补丁把同一边界应用于实际客户变化。

setTenant 在实际客户变化时清理客户草稿、调用已有 notifyAuthContext('tenant')，
使 App 的路由 key 销毁旧组件，Axios 丢弃旧版本响应。选择相同客户不重复失效。
不改变鉴权范围、后端 API 或部署流程。

`frontend/scripts/test-advisor-view-isolation.test.js` 新增真实 App/画像路由测试：
先载入合成客户 A，再切到读取 409 的客户 B，原实现仍显示 A 的摘要和业务资料；修复后消失。
真实 Axios adapter 另模拟 A→B→A 的延迟响应，原实现接受旧响应，修复后拒绝。
测试仅使用本地合成资料，没有访问业务服务。

独立后端补丁负责 archived 绑定的历史数据隔离。两条草稿 PR 本次均不合并、不 ready、不部署。

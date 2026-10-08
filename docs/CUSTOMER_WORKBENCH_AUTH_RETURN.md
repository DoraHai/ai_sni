# 客户工作台登录返回修复

2026-10-08。总控只读核对101：Auth current的RELEASE_COMMIT为63c67f379cc8907dc67965501fe64ef7ba340d69，编译产物的登录落点函数忽略redirect，固定回/workspace/cockpit。UI15本机生产bundle测试不能证明线上登录已支持新页面。

本变更仅Auth前端：显式同源/customer-workbench/返回地址、唯一且有效的tenant_id/site_id、无其他参数或fragment，且登录后的模块目录确认SEO available=true时，返回该范围。无参数的常规登录、其他旧模块入口、无SEO资格或目录失败仍按原行为进入旧cockpit。未开放通用任意redirect。

这是导航选择，不是租户授权；新工作台仍检查真实用户、模块、客户/站点和稿件权限。登录密码、验证码、session及权限接口未改，不触及数据库或SEO业务。

验证：10项重定向测试通过，覆盖既有落点、安全地址、有效新范围、模块不可用、重复/缺失/非法ID、外域和额外参数；build:auth和verify:auth-build通过。生产原登录与验证码需在正式上线窗口按最小验收清单执行，当前未部署。

发布使用既有Production Auth deployment和platform-deploy auth，仅合入codex/production-auth后才按现有流程部署。不与工作台静态包混装，不改线上编译文件。上线安排应包含本Auth修复、SEO代码及0105/0106迁移、工作台静态文件和路由。Auth回退到63c67f37会恢复旧cockpit落点，需要在记录中说明这一行为。

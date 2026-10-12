# 独立验收：发布记录存档读取

基线为 `e5e402a852e43431ada8143c13909bb466c2c2ba`。根窗口在实际 TLS/JWT 环境确认，短期单篇发布许可过期后，发布记录 GET 被入口门禁返回 403；该结果保存在私有 TEMP 的 `publication-reader-after-expiry-20261012.json`。本提交只解决存档读取，不声明原未知任务已发表或已核定未发表。

唯一新增的免短期许可入口是：

`GET /api/v1/seo/content-distribution/publications?tenant_id=15&site_id=6&content_id=61`

该入口必须属于指定 Linux 独立验收根目录、非生产配置、端口 55483/55861/55862，且原生 SEO 提交仍为 `3087e62f23e799fe82d279f79f698f0499bf3a27`。请求必须有 Bearer，并与工厂已装载的原生 `list_content_publications` GET handler 完全一致。三个查询参数只能各出现一次且值精确匹配；不接受其他参数、其他稿件、编码或追加路径。

原生 JWT、当前角色、模块、tenant/site 范围、真实数据库会话及存档 SELECT 查询继续执行。`include_router` 保留原 handler/依赖，并绑定独立工厂的数据库 dependency provider。空记录仍返回原生 `{items: [], total: 0, status_counts: {}}`。原生返回的动作资格只是说明；它不开放任何写接口。

`scripts/distribution_single_publication_gate.py`、原共享 core/auth/models、SEO/GEO 原生代码、source/digest、SQL 均无改动。publication-source/check/writeback/monitor、attempts、manual/complete/push、同路径 POST/HEAD 都不因此获准。GEO 不增加此接口。conversation/其他详情路由未新增。

本地定向回归为 **208 passed**：已有 174 项，加存档读取 34 项。测试包含原生冻结源码的只读 AST 核查及内存 ASGI 路由/依赖/权限哨兵，验证过期许可拒绝哨兵下存档读仍执行原身份/范围检查、独立会话绑定、错误范围/重复参数/伪路径/相邻写动作拒绝。它们不是实际 PG/JWT/TLS 或正式平台发布测试；部署后的真实客户与顾问读取由根窗口另验。

测试 XML 位于私有 TEMP：`distribution-stored-publications-read-tests-20261012/stored-publications-read.xml`，SHA256 为 `2b2cbee23775a0e4168ad73c61a4e093a0ca69cebc60da023b155e971b9937da`。

本开发窗口没有执行 API、数据库、云端服务、平台操作或单篇 helper，也没有改变已有 STATE/许可/任务。当前 account-verification 会话由根窗口和多号通控制，必须待其安全结束后由根窗口决定是否部署或重启；本提交不重启服务。

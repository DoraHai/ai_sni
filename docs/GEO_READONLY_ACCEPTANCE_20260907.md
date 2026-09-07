# GEO 普通身份只读验收记录

## 验收结论

- 验收时间：2026-09-07 00:46:54（Asia/Shanghai）
- 生产基线：`36b1b23`（验收时已部署版本；后续提交不自动继承本结论）
- 身份：`user_id=5`、`role_id=4`、`tenant_id=16`、`workbench_test_readonly`
- 权限：严格为约定的 6 个 `view` 权限：`monitor.dashboard`、`optimize.keywords`、`optimize.searchterms`、`seo.content`、`seo.site`、`geo.content`
- 结果：GEO 普通身份的五个只读接口均返回 HTTP 200，`invalid_count=0`
- 空配置状态：五项被检查资源均为 `configuration_initialized=false`、`persisted_count=0`

结合接口结果与持久化计数，本次只读调用没有为被检查的五项资源创建配置行。`configuration_initialized=false` 单独不能证明数据库没有写入，因此验收结论以 `persisted_count=0` 的联合证据为准。

## 边界

本记录只证明验收脚本覆盖的普通身份、权限收敛和五个 GEO 只读接口在上述部署基线下通过。它不覆盖问题与回答详情、六资源工作台完整调用链、真实采集、内容生成、再次检查、发布，也不代表 H1–H4 已通过。

后续部署新的 GEO 代码后，需要按新部署 SHA 重新执行只读健康验收。验收过程不记录令牌，不修改租户配置，不生成内容，不触发采集或发布。

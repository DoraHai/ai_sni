# GEO 独立发布基线

`codex/production-geo` 以负责人本地工作区代码为 GEO 功能来源。
线上文件和其他开发分支只用于差异核对，不得反向覆盖该基线。

## 发布边界

- GEO Vue 前端独立构建并发布到 `/opt/geo-frontend`。
- GEO API 独立发布到 `/opt/geo-service`，只重启 `geo-service`。
- 发布流程不修改或重启 `sem-backend`。
- SEO、SEM、诊断中心不包含在 GEO 发布流程中。
- 数据库迁移不随代码发布自动执行；生产迁移必须单独备份、审批和验证。

## 发布原则

1. 先通过 `GEO baseline check`。
2. 发布包必须记录 Git commit，禁止从服务器现有目录反向打包。
3. 健康检查失败时自动恢复 GEO 前后端上一版。
4. 生产数据库已使用的 Alembic 迁移链必须保留，不得因整理分支删除。

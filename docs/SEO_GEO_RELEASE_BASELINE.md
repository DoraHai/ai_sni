# SEO / GEO 发布基线

`codex/production-seo-geo-baseline` 以负责人本地工作区代码为 SEO、GEO
功能来源。线上文件和其他开发分支只用于差异核对，不得反向覆盖该基线。

## 当前边界

- GEO Vue 前端可独立构建。
- GEO API 使用独立的 `geo-service`，可独立重启。
- SEO 页面当前仍由综合前端构建。
- SEO API 当前仍由 `sem-backend` 提供。
- 在 SEO 前后端完全拆分前，不启用 SEO 自动生产发布。
- 数据库迁移不随代码发布自动执行；生产迁移必须单独备份、审批和验证。

## 发布原则

1. 先通过 `SEO and GEO baseline check`。
2. GEO、SEO 分别生成发布包，不直接同步整个工作区。
3. 发布包必须记录 Git commit，禁止从服务器现有目录反向打包。
4. GEO 发布不得重启 `sem-backend`；SEO 未拆分前保持锁定。
5. 生产数据库已使用的 Alembic 迁移链必须保留，不得因整理分支删除。

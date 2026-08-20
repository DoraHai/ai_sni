# 生产发布通道

生产发布使用独立账号 `platform-deploy`。GitHub Actions 只能通过
`/usr/local/sbin/platform-deploy` 调用 root 管理的模块入口，不授予任意 root 命令权限。

## 当前状态

- `production-connection-check.yml` 只验证 SSH、服务器身份和受限 sudo 通道。
- `geo`、`seo`、`sem`、`diagnostic`、`platform` 默认锁定。
- 连接检查不会上传代码、重启服务或执行数据库迁移。
- 正式发布入口必须在生产代码基线统一并完成模块回滚验证后单独安装、单独启用。
- 数据库迁移不会随模块发布自动执行，必须单独备份和审批。

## GEO 独立发布

GEO 发布入口只切换 `/opt/geo-service/current` 和
`/opt/geo-frontend/current`，只重启 `geo-service`，不会修改或重启
`sem-backend`。健康检查失败时自动恢复 GEO 前后端上一版。

首次配置时，以 root 身份在 `ops/platform-deploy` 目录执行：

```bash
bash install-geo.sh
```

以上命令只安装入口并保持锁定。核对 `platform-deploy status` 后，再执行：

```bash
bash install-geo.sh --enable
```

在 GitHub Actions 中选择 `Production GEO deployment`，必须从
`codex/production-geo` 分支运行并输入 `DEPLOY_GEO`。
发布包包含 GEO 独立前端和 `geo-service` 运行所需共享 Python 代码，
但只写入 GEO 的两个发布目录。流程不会运行 Alembic。

## 服务器安装

以 root 身份在仓库的 `ops/platform-deploy` 目录执行：

```bash
bash install.sh
```

安装过程会先备份已有 helper 与 sudoers 配置，再用 `visudo` 校验权限文件。

## GitHub 连接检查

在 Actions 中选择 `Production deployment connection check`，点击
`Run workflow`，输入 `CHECK`。成功输出应包含 `platform-deploy=ok`，且五个正式入口均为
`locked` 或 `not-configured`。

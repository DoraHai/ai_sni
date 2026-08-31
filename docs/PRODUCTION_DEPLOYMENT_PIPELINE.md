# 生产发布通道

生产发布使用独立账号 `platform-deploy`。GitHub Actions 只能通过
`/usr/local/sbin/platform-deploy` 调用 root 管理的模块入口，不授予任意 root 命令权限。

## 当前状态

- `production-connection-check.yml` 只验证 SSH、服务器身份和受限 sudo 通道。
- `geo`、`seo`、`sem`、`diagnostic`、`platform` 默认锁定。
- 连接检查不会上传代码、重启服务或执行数据库迁移。
- 正式发布入口必须在生产代码基线统一并完成模块回滚验证后单独安装、单独启用。
- 数据库迁移不会随模块发布自动执行，必须单独备份和审批。

## 服务器安装

以 root 身份在仓库的 `ops/platform-deploy` 目录执行：

```bash
bash install.sh
```

安装过程会先备份已有 helper 与 sudoers 配置，再用 `visudo` 校验权限文件。

SEM 后端模块必须从已审核的仓库提交单独安装，不能继续使用无法追溯的服务器侧脚本：

```bash
sudo bash ops/platform-deploy/install-sem.sh --enable
```

该安装器只备份并原子更新 `/etc/platform-deploy/modules/sem` 及其启用标记，
不会发布代码、切换 `/opt/sem-backend/current`、重启服务或执行 Alembic。使用
`--locked` 可安装模块但保持发布入口锁定。正式 `apply sem` 会把校验通过的
`MANIFEST` 和 `RELEASE_COMMIT` 以 root 只读文件持久化到新 release，并在健康检查中
确认运行中的 `release_commit` 与请求 SHA 完全一致。

## GitHub 连接检查

在 Actions 中选择 `Production deployment connection check`，点击
`Run workflow`，输入 `CHECK`。成功输出应包含 `platform-deploy=ok`，且五个正式入口均为
`locked` 或 `not-configured`。

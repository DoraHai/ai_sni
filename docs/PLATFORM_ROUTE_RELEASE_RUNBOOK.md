# Platform 路由受限发布说明

适用分支：`codex/production-sem`。Platform 路由发布只更新受审 Nginx 配置，
不包含前端、后端、数据库迁移或客户数据操作。

## 权威分支校验

服务器端 `platform` 模块持有 `/run/lock/platform-route-deploy.lock` 后，直接对
`https://github.com/DoraHai/ai_sni.git` 的
`refs/heads/codex/production-sem` 执行 `git ls-remote --refs`。它不接受 runner
传入的分支头、缓存结果或本地 remote-tracking ref。

每个发布边界最多查询三次。只有 `git ls-remote` 网络失败才等待两秒后重试；一次成功查询
必须恰好返回一行、一个小写 40 位 SHA 和完全相同的 ref。空结果、格式错误、多行、ref 不符
或 SHA 与待发布提交不符均立即关闭。第一次校验位于发布归档前，第二次校验位于归档发布及
Nginx 配置变更的最终边界前。网络重试耗尽仍以状态 64 退出。

## 安装受审模块

合并后先从 `codex/production-sem` 的干净、精确提交检出以下文件，并核对工作区无改动：

- `ops/platform-deploy/install-platform-routes.sh`
- `ops/platform-deploy/modules/platform`

当前受审模块 SHA-256：

```text
c8824ba23eb0efdd57f9c6a0027685f3d2da7a99d39a09cef54d8e639493639d
```

安装器会在写入 `/etc/platform-deploy/modules/platform` 前同时校验 dispatcher 和上述模块
哈希，任一不符即停止。由服务器管理员执行：

```bash
sudo -n ops/platform-deploy/install-platform-routes.sh --enable
sudo -n /usr/local/sbin/platform-deploy status
sha256sum /etc/platform-deploy/modules/platform
```

应记录安装器输出的备份目录、`platform=enabled` 与模块 SHA-256。不要直接编辑服务器上的
module 文件。

## 重新发布与验收

安装完成后，使用 GitHub Actions 的 `Production SEM platform routes` workflow 发布当前
`codex/production-sem` 精确提交。不得复用失败 run 的 artifact、runner 分支头或旧 SHA。

成功记录应包含服务器输出的 commit、active SHA-256、备份目录，以及 `/platform`、
`/platform/customers`、`/platform/accounts`、`/platform/roles`、旧设置入口、获客工作台、
SEM 看板与关键词页的 smoke 结果。若权威查询最终失败，应确认没有发布归档、Nginx 配置、
reload 或公网 smoke 操作，然后另起 workflow attempt；不能跳过服务器权威校验。

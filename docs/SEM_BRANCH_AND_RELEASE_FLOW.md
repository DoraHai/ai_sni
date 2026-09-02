# SEM 分支职责与发布关系

> 适用范围：Growth Sniper 的 SEM 开发、审核和生产发布。
>
> 更新日期：2026-09-02。
>
> 本文记录当前已经实施的分支拆分。仓库中部分早期交接材料仍将
> `codex/production-sem` 描述为整个 SEM 系统的开发基线，那是历史状态；新任务应以本文和
> 负责人最新确认的发布规则为准。`AGENTS.md` 属于全仓库规则，修改前仍需单独审核。

## 1. 永久分支

| 分支 | 职责 | 是否直接开发 | 合入后的效果 |
| --- | --- | --- | --- |
| `main` | 所有模块审核通过代码的集成主线，也是 SEM 功能分支的开发基线 | 否 | 不代表把整个 `main` 部署到任一 SEM 生产单元 |
| `codex/production-sem` | SEM **前端**生产发布基线 | 否 | 合并经过审核的前端同步 PR 后，触发现有 SEM 前端发布流程 |
| `codex/production-sem-backend` | SEM **后端**生产发布基线 | 否 | 更新分支本身不自动发布；从 `main` 手动运行后端发布 workflow 才会发布 |

三条永久分支不能互相替代：

```text
最新 main
   │
   ├─ codex/sem-<task-name>          功能开发与 PR 审核
   │          │
   │          └───────────────PR──▶ main
   │                                  │
   │                                  ├─前端同步 PR──▶ codex/production-sem
   │                                  │                 └─自动发布 SEM 前端
   │                                  │
   │                                  └─后端同步 PR──▶ codex/production-sem-backend
   │                                                    └─人工输入完整 SHA
   │                                                      手动发布 SEM 后端
   └─不允许把 main 整体直接部署到 SEM 生产
```

## 2. 日常 SEM 功能分支

每个独立任务从最新远程 `main` 新建一个分支：

```bash
git fetch origin --prune
git switch --create codex/sem-<task-name> origin/main
```

功能分支必须保持单一职责：

- 只包含当前 SEM 任务需要的代码、测试和文档；
- 不顺手修改或发布 SEO、GEO、诊断中心和门户；
- 不修改 `app/baidu/**`，除非 SEM 任务明确需要并已经获得授权；
- 不提交 `.env`、密钥、Token、数据库文件、构建缓存或本地文件；
- 测试通过后创建 PR 合入 `main`，不直接推送到任何生产分支；
- 已合并的功能分支属于历史记录，不继续复用开发下一项任务。

当前任务使用：

```text
codex/sem-live-write-gate-hardening
```

它只负责完善按客户真实回写门禁，不是生产分支，合入或推送该分支都不会触发生产发布。

## 3. SEM 前端发布

前端发布只使用 `codex/production-sem`：

1. SEM 前端功能 PR 先审核并合入 `main`；
2. 从已合入 `main` 的提交创建独立前端同步 PR；
3. 同步 PR 的目标分支为 `codex/production-sem`；
4. 审核确认只包含本次需要发布的 SEM 前端文件；
5. 合并后由现有 SEM 前端 workflow 自动发布；
6. 不重跑旧 workflow，避免旧提交覆盖新版本；
7. 发布后核对页面、路由和实际静态资源版本。

`codex/production-sem` 不允许用于：

- SEM 后端发布；
- 普通功能开发；
- SEO、GEO、诊断中心或门户发布；
- 直接合入未经 `main` 审核的代码。

## 4. SEM 后端发布

后端发布只使用 `codex/production-sem-backend`：

1. SEM 后端功能 PR 先审核并合入 `main`；
2. 创建独立后端同步 PR，只带入审核过的 SEM 后端提交；
3. 同步 PR 的目标分支为 `codex/production-sem-backend`；
4. 合并后读取该远程分支的完整 40 位 SHA；
5. 从 `main` 手动运行 `Production SEM backend deployment`；
6. 输入 `release_sha=<后端生产分支完整 SHA>`；
7. 输入 `confirmation=DEPLOY_SEM_BACKEND`；
8. workflow 三次核对远程后端生产分支 HEAD，任何一次变更都停止旧任务；
9. workflow 只能调用 `platform-deploy apply sem`；
10. 服务器负责创建新 release、原子切换、只重启 `sem-backend`、健康检查和失败回滚。

后端生产分支更新不等于已经部署。是否上线以受控 workflow 结果、服务器 release manifest 和
`/health` 中的 `RELEASE_COMMIT` 为准。

后端 release manifest 必须记录：

```text
module=sem
commit=<release_sha>
migration=not-run
```

## 5. 数据库与共享基础设施边界

普通 SEM 前端或后端发布均不得：

- 执行 `alembic upgrade`、`alembic downgrade` 或 `alembic stamp`；
- 自动修改、清空、回填或覆盖生产数据；
- 把数据库迁移隐藏在后端发布流程中；
- 修改或 reload Nginx；
- 部署或重启 SEO、GEO、诊断中心、门户及其他服务。

如果功能确实需要 Schema 变化，必须先做只读诊断，单独列出表、字段、索引、约束、数据兼容、
迁移风险和回滚方式；获得负责人明确批准后，再走独立数据库流程。

Nginx 变更同样属于独立发布单元，必须经过专门 PR 和受控运维步骤：备份、对比、`nginx -t`、
reload、真实响应验收。不能借 SEM 前端或后端 workflow 顺带发布。

## 6. 临时同步分支与历史分支

仓库中大量 `codex/sem-*` 分支来自已完成的功能、修复或生产同步任务。判断方式如下：

- `codex/sem-<task-name>`：普通功能/修复分支，PR 合并后即停止继续开发；
- 名称含 `frontend-sync`、`backend-sync`、`production-sync` 或 `release`：某一次发布的临时同步分支，
  只服务于对应 PR，不是长期生产基线；
- 已关闭或已合并 PR 对应的分支：仅保留历史追溯价值；
- 只有 `main`、`codex/production-sem`、`codex/production-sem-backend` 是当前 SEM 流程中的永久分支。

不要仅凭分支名判断是否已发布，也不要在旧分支上继续追加新功能。应检查 PR、远程 HEAD、workflow
记录和生产 manifest 四项证据。

## 7. 当前基线快照

截至 2026-09-02，本任务建立时读取到：

| 对象 | SHA | 说明 |
| --- | --- | --- |
| `origin/main` | `e0d8e8b7898aba5d2b598f51d3209edd55a084cb` | 当前功能开发基线；包含按客户真实回写门禁 PR #196 |
| `origin/codex/production-sem-backend` | `31f1e705497d853f64f655308c08faa85038ebfb` | 后端生产分支当前 HEAD；对应同步 PR #198 |
| `origin/codex/production-sem` | `cfd8c82aa70733cdc08a90971469c71cb60b6a2a` | 前端生产分支当前 HEAD；对应同步 PR #199，实际线上版本仍以发布记录为准 |

以上 SHA 是交接快照，不应长期写死到脚本。每次开发或发布前必须重新读取远程状态：

```bash
git fetch origin --prune
git rev-parse origin/main
git rev-parse origin/codex/production-sem
git rev-parse origin/codex/production-sem-backend
```

## 8. 禁止事项速查

- 禁止直接在 `main` 或两条生产分支上开发；
- 禁止强推或覆盖生产分支；
- 禁止把 `main` 全量同步到某个 SEM 生产分支；
- 禁止绕过同步 PR，把未经审核的提交直接推入生产基线；
- 禁止用 SEM 前端生产分支发布后端；
- 禁止用 SEM 后端 workflow 发布前端或其他模块；
- 禁止手动修改服务器 release 目录或 `current` 软链接；
- 任一门禁、SHA、测试或健康检查失败时立即停止，不绕过检查。

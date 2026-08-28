# Growth Sniper / SEM 平台开发交接手册

> 历史交接基线：`codex/handoff-sem-20260813`；当前开发从最新 `main` 建分支，见 2.1 节
>
> 整理日期：2026-08-13
>
> 生产主域名：<https://gsnipers.snipers.com.cn>（`sem.snipers.com.cn` 仅保留兼容跳转）

## 1. 接手人先看这里

这是一个多租户获客运营平台，主要包含 SEM、SEO、GEO、统一登录和官网门户。后端
基于 FastAPI + PostgreSQL，前端基于 Vue 3 + Vite。生产环境已经按发布单元拆分，
**不要把不同前端的构建产物同步到同一个目录**。

接手第一周建议按下面顺序操作：

1. 拉取最新 `main`，从它创建独立功能分支并完成本地启动，不要直接在 `main` 开发；
2. 使用测试租户验证登录、客户切换和权限菜单；
3. 在测试账号上跑一遍百度服务商 OAuth，不接触客户真实密码；
4. 执行完整后端测试和三套前端构建；
5. 仅在负责人确认后做一次测试发布和回滚演练；
6. 熟悉数据库备份后，再执行任何 Alembic 迁移。

## 2. 代码与分支

- GitHub：`DoraHai/ai_sni`
- SSH remote：`git@github-dorahai:DoraHai/ai_sni.git`
- 当前开发基线：远程最新 `main`
- 历史交接基线：`codex/handoff-sem-20260813`（仅用于追溯 2026-08-13 状态）
- 不要使用未同步的本地旧 `main`，也不要强推覆盖远程 `main`。

推荐工作流：

```bash
git clone git@github-dorahai:DoraHai/ai_sni.git
cd ai_sni
git fetch origin --prune
git switch main
git pull --ff-only origin main
git switch -c codex/sem-<任务名>
```

提交前至少执行第 8 节的验证。通过 Pull Request 合并，不直接向生产基线强推。

### 2.1 当前权威 SEM 分支与发布流程（2026-08-28）

本节覆盖本文档中更早形成的 SEM 分支和发布说明；旧快照只用于理解历史，不能作为当前
生产操作依据。

分支职责：

- `main`：所有审核通过的代码最终合入这里，但不得把 main 的全部内容整体部署到 SEM 生产。
- `codex/production-sem`：只用于 SEM 前端生产发布。审核后的 SEM 前端提交通过独立同步 PR
  合入；合并会触发现有 SEM 前端自动部署。该分支不得用于发布 SEM 后端。
- `codex/production-sem-backend`：只用于 SEM 后端生产发布基线。2026-08-28 建立时的精确基线为
  `43b6123bcead2f3183f1c562ff0168d21f25ddda`，与当时生产 `sem-backend` 一致。更新该分支不会
  自动部署；禁止强推、直接覆盖或混入未经审核的 GEO、SEO、诊断中心和门户改动。

日常 SEM 开发：

1. 从最新 `main` 创建独立分支 `codex/sem-<task-name>`；
2. 只修改任务必需的 SEM 文件，不顺手修改其他模块；除非任务明确授权，不修改
   `app/baidu/**`；
3. 不提交 `.env`、密钥、数据库文件、构建缓存或本地文件；
4. 完成本地测试和审核后，通过 PR 合入 `main`。

SEM 前端发布：

1. 只选择已合入 `main` 且属于 SEM 前端的审核提交；
2. 通过独立同步 PR 合入 `codex/production-sem`；
3. 合并后由现有 SEM 前端 workflow 自动部署，不手工拼接 release；
4. 不重跑旧 workflow，避免旧提交回退线上版本；
5. 发布后验收 SEM 页面和实际静态资源版本。

SEM 后端发布：

1. 后端功能 PR 先合入 `main`；
2. 再创建独立同步 PR，把审核后的 SEM 后端提交同步到
   `codex/production-sem-backend`，禁止未经审核直接 push 或强推；
3. 确认远程后端生产分支的完整 40 位 SHA；
4. 从 `main` 手动运行 GitHub Actions 的 `Production SEM backend deployment`；
5. 输入 `release_sha=<后端生产分支完整 SHA>` 和
   `confirmation=DEPLOY_SEM_BACKEND`，完成 `production` environment 审批；
6. workflow 必须在开始、上传前和 apply 前通过三次后端生产分支 stale HEAD 检查；
7. workflow 只能调用 `platform-deploy apply sem`。服务器端负责建立新 release、原子切换
   `current`、只重启 `sem-backend`、检查内部 `/health` 和 `db=ok`，失败时恢复旧 current；
8. 发布后确认 `sem-backend` active、公开 `/health` 返回 200、`db=ok`、`RELEASE_COMMIT`
   等于目标 SHA，并确认 MANIFEST 记录 `migration=not-run`。

数据库和跨模块红线：

- 普通 SEM 前端或后端发布不得执行 `alembic upgrade`、`downgrade` 或 `stamp`，也不得把迁移
  隐藏在后端自动部署中；
- 确需 Schema 变更时，先只读检查生产 revision 和实际 Schema，单独汇报表、字段、索引、
  约束、回填、兼容性、回滚风险，得到明确授权后再走独立受控流程；
- 后端 workflow 不部署 SEM 前端、GEO、SEO、诊断中心、门户或 Nginx，也不重启其他服务；
- 除非任务是经审核的 Nginx 发布，不修改或 reload Nginx；
- 不手动修改 `/opt/*/releases` 或 `current`，任何门禁失败都应立即停止并汇报。

当前状态：PR #117 已合入 `main`，SEM 后端手动发布流程已经建立；生产 `sem-backend` 与
`codex/production-sem-backend` 均为 `43b6123bcead2f3183f1c562ff0168d21f25ddda`，不需要因流程
建立而重复运行 workflow 或重新部署。

## 3. 系统结构

| 目录/服务 | 技术与职责 | 生产位置 |
| --- | --- | --- |
| `app/` | FastAPI 主后端；SEM、登录、百度 OAuth、SEO API、报表 | `/opt/sem-backend`，`sem-backend.service`，端口 8000 |
| `app/geo_main.py` | GEO 独立 API 入口及独立调度器 | `/opt/geo-service/current`，`geo-service.service`，端口 8010 |
| `frontend/` | SEM 主 SPA，以及各独立前端构建配置 | 见下方发布单元 |
| `frontend/auth/` | 公共登录入口 | `/opt/auth-frontend/current` |
| `frontend/geo-frontend/` | GEO 独立前端 | `/opt/geo-frontend/current` |
| `migrations/` | 共享 PostgreSQL 的 Alembic 迁移 | 发布前人工审核和执行 |
| `deploy/` | Nginx、systemd 和服务器说明 | 服务器 `/etc/nginx`、`/etc/systemd/system` |
| `tests/` | 后端自动化测试 | 本地/CI |

核心生产路由：

| URL | 服务/静态目录 |
| --- | --- |
| `/login`、`/auth-assets/*` | 独立登录前端 |
| `/api/*` | SEM 主后端 8000 |
| `/api/oauth/baidu/callback` | 百度服务器 OAuth 回调，必须公开可达 |
| `/api/v1/geo/*`、`/geo-health` | GEO API 8010 |
| `/deal-sniper/geo/*` | GEO 独立前端 |
| 其他后台路由、`/assets/*` | SEM 主前端 |

统一登录目前与业务模块同域，通过 `localStorage/sessionStorage` 保存 JWT。未登录时业务
应用会带 `redirect` 参数跳转 `/login`，登录成功后返回原页面。

## 4. 本地开发

### 4.1 环境要求

- Python 3.11+（建议与生产虚拟环境版本一致）
- Node.js 与 npm（必须使用 `npm ci`）
- PostgreSQL 16，或使用项目中的 Docker Compose
- Git、Docker、Alembic

### 4.2 启动数据库与后端

```bash
docker compose up -d postgres
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`.env.example` 只列变量名和本地示例。生产 SecretKey、Token、数据库密码、JWT 密钥
不得通过 Git、文档或聊天明文传递。

### 4.3 启动 SEM 与公共登录页

```bash
cd frontend
cp .env.example .env.development
npm ci

# 终端一：SEM 主前端 http://127.0.0.1:5173
npm run dev

# 终端二：公共登录页 http://127.0.0.1:5174/login
npm run dev:auth
```

本地未配置 `VITE_API_KEY` 时按真实登录流程测试。生产构建禁止嵌入 `VITE_API_KEY`。

### 4.4 启动 GEO API

```bash
source .venv/bin/activate
uvicorn app.geo_main:app --reload --host 127.0.0.1 --port 8010
```

GEO 使用同一个数据库和认证表，但 API 进程、调度器、前端发布与 SEM 分离。

## 5. 配置与凭据交接

生产 `.env` 在服务器 `/opt/sem-backend/.env`，由
`sem-backend.service` 和 `geo-service.service` 共用。凭据应通过企业密码管理器交接，
接手人只获得岗位需要的权限。

必须单独交接的系统：

- GitHub 仓库协作者权限；
- 生产服务器独立 SSH 账号，日常不要共享 root；
- PostgreSQL：先给只读账号，发布负责人再持有迁移权限；
- 百度营销商业开发者中心及服务商应用；
- 域名/DNS、SSL、云服务器与数据库控制台；
- 生产日志和监控权限；
- 密码管理器中的生产环境变量。

关键环境变量分类：

- 基础：`APP_ENV`、`APP_BASE_URL`、`DATABASE_URL`；
- 登录：`JWT_SECRET`、`JWT_EXPIRE_HOURS`、`ADMIN_API_KEY`；
- 百度：`BAIDU_APP_ID`、`BAIDU_SECRET_KEY`、`BAIDU_OAUTH_SCOPE`、回调地址；
- 加密：`CRYPTO_MASTER_KEY_B64`；
- GEO：站长、PageSpeed、Lighthouse、DashScope/DeepSeek 相关 Key。

禁止事项：

- 禁止提交 `.env`、OAuth Token、百度 SecretKey、数据库口令；
- 禁止让 `JWT_SECRET` 与 `ADMIN_API_KEY` 相同；
- 禁止更换 `CRYPTO_MASTER_KEY_B64` 后直接重启，需先按密钥轮换脚本处理存量密文；
- 禁止把服务端 Key 写入 `VITE_*`。

## 6. 百度服务商 OAuth 与数据同步

入口：登录后进入 `/onboarding`，点击“授权新客户账号”。

正常流程：

1. 后端生成带签名 `state` 的百度授权链接；
2. 用户在百度页面选择推广账号并同意授权；
3. 百度回调 `/api/oauth/baidu/callback`；
4. 后端验签、换取并加密保存 Token；
5. 创建或绑定新租户与百度账户；
6. 首次同步后自动切换到新客户。

平台不保存客户百度账号密码。Token 使用 `CRYPTO_MASTER_KEY_B64` 加密，失效或客户解除
授权后停止同步并提示重新授权。

SEM 主调度器在 `app/scheduler.py`：

- 每 15 分钟同步当日关键词工作台与报告；
- 每日执行昨日数据和派生分析；
- 使用进程文件锁避免多 worker 重复调度；
- 手动刷新也使用租户锁，避免与定时任务并发覆盖。

排查顺序：授权状态 → Token 过期/刷新 → 百度账户状态 → 调度日志 → 数据库
`last_synced_at` / `last_sync_error`。

## 7. 数据库迁移

所有模块共享同一个 PostgreSQL。迁移是高风险操作，不属于普通 SEM 前端或后端发布步骤，
也不得由 SEM 自动发布 workflow 执行。普通发布固定记录 `migration=not-run`。

只有功能确定需要 Schema 变更并获得负责人明确授权后，才能进入独立迁移流程。授权前先只读
检查生产 revision 和实际 Schema，并单独汇报表、字段、索引、约束、数据回填、兼容性和回滚风险。

经授权的独立迁移流程在执行前才检查：

```bash
alembic heads
alembic current
alembic history --verbose
```

要求：

1. 迁移文件必须进入同一个 PR；
2. 确认 Alembic 只有预期 head，出现多 head 时先建立显式 merge migration；
3. 生产执行前做数据库快照或 `pg_dump`；
4. 在备份确认可恢复后执行 `alembic upgrade head`；
5. 迁移后先跑健康检查，再重启/发布服务；
6. 不应仅依赖 downgrade，涉及数据变换时需另写恢复方案。

当前交接分支包含 SEO 基础迁移：

- `20260809_0056_seo_foundation.py`
- `20260810_0057_seo_rewrite_workflow.py`

这组 SEO 改动在交接整理时仍属于开发中基线，**尚未因本次交接而部署生产**。

## 8. 测试与发布门禁

后端：

```bash
source .venv/bin/activate
PYTHONPATH=. pytest -q
```

可以先跑与当前开发内容最相关的测试：

```bash
PYTHONPATH=. pytest -q tests/test_seo_foundation.py tests/test_geo_chinaz.py tests/test_geo_site_audit.py
```

如果本机没有开发 `.env`，测试收集会因必填配置缺失而终止。应使用测试专用环境变量或
CI Secret，不能借用生产 `.env`。交接整理时上述三组测试结果为 **40 passed**，完整
后端测试结果为 **297 passed**。

前端：

```bash
cd frontend
npm ci
npm run build
npm run verify:sem-build
npm run build:auth
npm run verify:auth-build
npm run build:diagnostic-center

cd geo-frontend
npm run build
```

交接整理时，上述 SEM、登录页、诊断中心与 GEO 前端构建全部成功；Vite 仍会提示部分
chunk 超过 500 kB，属于后续性能优化项，不影响本次构建通过。

部署前只校验、不上传：

```bash
VERIFY_ONLY=1 npm run deploy:sem
VERIFY_ONLY=1 npm run deploy:login
```

若测试因外部 API、浏览器或真实凭据缺失而跳过/失败，必须在 PR 中记录原因，不得写成
“全部通过”。

## 9. 生产发布与回滚

任何生产发布都应先取得负责人确认。推荐顺序：数据库备份/迁移 → API → 独立前端 →
健康检查与业务抽测。

### 9.1 公共登录页

```bash
cd frontend
npm run deploy:login
```

独立发布到 `/opt/auth-frontend/releases/<时间戳>`，原子切换 `current`。它不会覆盖 SEM。

### 9.2 SEM 主前端

只把已合入 `main` 的 SEM 前端审核提交通过独立同步 PR 合入 `codex/production-sem`。合并后由
现有 SEM 前端 workflow 自动发布到 `/opt/sem-frontend/releases/<时间戳>`。不要直接运行旧发布
任务或重跑旧 workflow；发布后核对页面和实际静态资源版本。

### 9.3 SEM 后端

只把已合入 `main` 的 SEM 后端审核提交通过独立同步 PR 合入
`codex/production-sem-backend`。确认完整 SHA 后，从 `main` 手动运行
`Production SEM backend deployment`，输入该 SHA 和 `DEPLOY_SEM_BACKEND`，并通过生产环境审批。
workflow 不执行 Alembic，只调用受限的 `platform-deploy apply sem`；不要手工修改 release 或
`current`。

### 9.4 GEO

详见 `deploy/README-GEO-INDEPENDENT.md` 和 `docs/GEO_PRODUCTION_RUNBOOK.md`。

```bash
scripts/deploy_geo_api.sh
cd frontend/geo-frontend && npm run deploy
```

GEO API 发布失败会尝试自动恢复上一条 `current` 并仅重启 `geo-service`。

### 9.5 回滚

前端和 GEO API 均使用版本目录。确认目标版本后，将对应 `current` 链接原子指回上一
版本；API 回滚后重启对应 systemd 服务。不要删除当前版本后再回滚。

SEM 主后端仍位于 `/opt/sem-backend`，变更前先保留代码和数据库备份。涉及数据库结构
时，必须按迁移恢复方案处理，不能只回滚代码。

### 9.6 发布后检查

```bash
curl -fsS https://gsnipers.snipers.com.cn/health
curl -fsS https://gsnipers.snipers.com.cn/geo-health
curl -fsSI https://gsnipers.snipers.com.cn/login
curl -fsSI https://gsnipers.snipers.com.cn/onboarding
```

同时检查：

```bash
systemctl status sem-backend
systemctl status geo-service
nginx -t
journalctl -u sem-backend -n 200 --no-pager
journalctl -u geo-service -n 200 --no-pager
```

## 10. 交接整理时的生产状态

2026-08-13 只读检查结果：

- `nginx`：active，配置语法通过；
- `sem-backend`：active，`/health` 返回 `env=prod, db=ok`；
- `geo-service`：active，`/health/geo` 返回 `env=prod, db=ok`；
- SEM 前端：`/opt/sem-frontend/releases/20260809T161643Z`；
- 登录前端：`/opt/auth-frontend/releases/20260805T141104Z`；
- GEO API：`/opt/geo-service/releases/20260808T142216Z`；
- GEO 前端：`/opt/geo-frontend/releases/20260808T085740Z`。

以上只是交接时快照，排障时应重新检查，不要长期假定仍是这些版本。

## 11. 当前开发中内容与已知风险

交接分支在既有集成基线上增加了：

- SEO 数据模型、API、权限、迁移与 Vue 工作台；
- SEO 关键词资产、内容改写和站内优化页面；
- 部分 GEO 站点审计/站长数据修正和相关测试；
- 对统一门户、路由和菜单的配套调整。

接手后应重点确认：

1. SEO 两个迁移在全新数据库和现有数据库都能升级；
2. SEO 权限是否已加入所有内置角色，而非仅管理员；
3. SEO 页面 API 是否全部按当前租户隔离；
4. GEO 与 SEM 独立发布后，主应用路由没有重复或覆盖；
5. 当前大量原型 HTML 与 Vue 页面并存，后续应确定唯一实现，避免两处同步维护；
6. `frontend/README.md` 仍是 Vite 模板说明，开发以根目录 README 和本手册为准；
7. 发布脚本默认生产主机，执行 `deploy:*` 前必须确认目标和负责人授权。

## 12. 最小交接验收

代码接手不以“拿到压缩包”为完成标准。接手人应现场完成：

- 从远程交接分支重新克隆；
- 本地启动 PostgreSQL、FastAPI、SEM 和登录页；
- 使用测试账号登录并切换租户；
- 完成一次测试百度 OAuth 或至少走到官方授权页；
- 跑完后端测试和前端构建；
- 说明三套前端为何必须独立发布；
- 在非生产环境做一次发布和回滚；
- 能找到生产健康检查、日志和数据库备份入口。

完成后，原开发者再撤销不必要的个人凭据和共享 root 权限。

# Growth Sniper / SEM 平台开发交接手册

> 交接基线：`codex/handoff-sem-20260813`
>
> 整理日期：2026-08-13
>
> 生产域名：<https://sem.snipers.com.cn>

## 1. 接手人先看这里

这是一个多租户获客运营平台，主要包含 SEM、SEO、GEO、统一登录和官网门户。后端
基于 FastAPI + PostgreSQL，前端基于 Vue 3 + Vite。生产环境已经按发布单元拆分，
**不要把不同前端的构建产物同步到同一个目录**。

接手第一周建议按下面顺序操作：

1. 从交接分支克隆并完成本地启动，不要直接在 `main` 开发；
2. 使用测试租户验证登录、客户切换和权限菜单；
3. 在测试账号上跑一遍百度服务商 OAuth，不接触客户真实密码；
4. 执行完整后端测试和三套前端构建；
5. 仅在负责人确认后做一次测试发布和回滚演练；
6. 熟悉数据库备份后，再执行任何 Alembic 迁移。

## 2. 代码与分支

- GitHub：`DoraHai/ai_sni`
- SSH remote：`git@github-dorahai:DoraHai/ai_sni.git`
- 推荐接手基线：`codex/handoff-sem-20260813`
- 基线来源：`integrate-geo-origin-main-20260808`
- 本地 `main` 曾长期分叉，不应作为新开发起点，也不要强推覆盖远程 `main`。

推荐工作流：

```bash
git clone git@github-dorahai:DoraHai/ai_sni.git
cd ai_sni
git switch codex/handoff-sem-20260813
git pull --ff-only
git switch -c feature/<任务名>
```

提交前至少执行第 8 节的验证。通过 Pull Request 合并，不直接向生产基线强推。

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

所有模块共享同一个 PostgreSQL。迁移是高风险操作，不属于普通前端发布步骤。

发布前：

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

```bash
cd frontend
npm run deploy:sem
```

独立发布到 `/opt/sem-frontend/releases/<时间戳>`。脚本会校验 OAuth 页面存在，并拒绝
包含登录页的错误构建。

### 9.3 GEO

详见 `deploy/README-GEO-INDEPENDENT.md` 和 `docs/GEO_PRODUCTION_RUNBOOK.md`。

```bash
scripts/deploy_geo_api.sh
cd frontend/geo-frontend && npm run deploy
```

GEO API 发布失败会尝试自动恢复上一条 `current` 并仅重启 `geo-service`。

### 9.4 回滚

前端和 GEO API 均使用版本目录。确认目标版本后，将对应 `current` 链接原子指回上一
版本；API 回滚后重启对应 systemd 服务。不要删除当前版本后再回滚。

SEM 主后端仍位于 `/opt/sem-backend`，变更前先保留代码和数据库备份。涉及数据库结构
时，必须按迁移恢复方案处理，不能只回滚代码。

### 9.5 发布后检查

```bash
curl -fsS https://sem.snipers.com.cn/health
curl -fsS https://sem.snipers.com.cn/geo-health
curl -fsSI https://sem.snipers.com.cn/login
curl -fsSI https://sem.snipers.com.cn/onboarding
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

## 13. SEO 百度排名小批量验收修复（2026-09-01）

- 验收对象：诺德现有 8 个启用关键词，百度 PC/移动各一次，共 16 个供应商请求。
- 已修复站长之家批量请求节流：请求改为单连接串行，每次间隔 1 秒；HTTP 436 与 429
  均按限流处理并进行有界重试，避免小批量请求瞬时并发触发供应商拦截。
- 每天 02:00 自动排名采集改为默认关闭；只有小批量真人验收通过后，才在生产环境显式设置
  `SEO_RANK_SCHEDULER_ENABLED=true`。
- 验收前不得打开自动采集。验收结果应记录 16 次请求的成功数、失败数、错误码，分别确认
  PC/移动快照入库，并确认失败请求不会消耗成功额度。

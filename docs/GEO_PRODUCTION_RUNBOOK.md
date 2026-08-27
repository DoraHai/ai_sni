# GEO 真实服务器上线步骤（产品化必做 · 第三步）

> 适用：生产 / 预发 **Linux 主机**（与仓库 `deploy/*` 默认路径一致）  
> 关联：`docs/GEO_DELIVERY_CHECKLIST.md` §4.2 · `deploy/README-GEO-INDEPENDENT.md`  
> 工程侧门禁（本地/CI）见 `scripts/verify_productization_must.py`；**本文件只写机上操作**。  
>  
> **若无生产机、仅做 GEO 代码交付**：不必执行本文。请以 **`docs/GEO_CODE_DELIVERY.md`** 为准完成交接；本文留给接收方日后上线使用。

---

## 0. 角色与范围

| 角色 | 负责 |
| --- | --- |
| 运维 | 主机、Nginx、systemd、备份、密钥落盘权限 |
| 研发 | 发布包/分支、迁移评审、业务抽测 |
| 产品/交付 | 主环手测签字（登录后走一遍） |

**范围：**

- 共享 Postgres（与 SEM 同库）
- 主站 API：`sem-backend`（默认 `127.0.0.1:8000`，**含 scheduler / 可见度定时巡检**）
- GEO 独立 API：`geo-service`（`127.0.0.1:8010`，**不**启 SEM 调度）
- 静态 GEO 前端：`/opt/geo-frontend/current` → 公网 `/deal-sniper/geo/*`
- Vue 主站 SPA：按主站现有发布流程（**禁止**生产构建写入 `VITE_API_KEY`）

**刻意不在此文档：** 社交 OAuth、代理商 ZIP 交付包、改百度写回红线。

---

## 1. 上线前检查（T-1）

在**发布机或本机**确认要发布的代码已含：

- 迁移 `0052_geo_vis_patrol`、`0053_patrol_window`（及之前 head）
- `app/security/prod_guard.py`（`APP_ENV=prod` 密钥硬拦截）
- 可见度巡检 API / 前端（`/geo/visibility/patrol`）

```bash
# 发布前在 CI 或研发机（非生产密钥）
python -m pytest -q tests
python scripts/verify_productization_must.py
```

确认目标主机可 SSH，且已有用户 `sem`（与 `deploy/setup-geo.sh` 一致）。

默认部署目标变量（可按环境覆盖）：

| 变量 | 默认含义 |
| --- | --- |
| `DEPLOY_TARGET` | 如 `root@你的主机`（见 `scripts/deploy_geo_api.sh`） |
| GEO API 根 | `/opt/geo-service` |
| GEO 前端根 | `/opt/geo-frontend` |
| 共享 `.env` | `/opt/sem-backend/.env` |
| GEO 监听 | `127.0.0.1:8010` |
| 主站监听 | `127.0.0.1:8000` |

---

## 2. 备份（必须先做）

在**目标服务器**上：

```bash
# 2.1 记录当前版本
systemctl is-active sem-backend geo-service nginx || true
readlink -f /opt/geo-service/current 2>/dev/null || true
readlink -f /opt/geo-frontend/current 2>/dev/null || true

# 2.2 Postgres 逻辑备份（库名/账号按实际 .env 中 DATABASE_URL 修改）
sudo -u postgres mkdir -p /var/backups/sem
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
sudo -u postgres pg_dump -Fc -f "/var/backups/sem/sem_pre_geo_${STAMP}.dump" sem_prod
ls -lh "/var/backups/sem/sem_pre_geo_${STAMP}.dump"

# 2.3 备份当前 .env（不含提交到 git）
sudo cp -a /opt/sem-backend/.env "/var/backups/sem/env_${STAMP}.bak"
sudo chmod 600 "/var/backups/sem/env_${STAMP}.bak"
```

**勾选：**

- [ ] Dump 文件非空且可 `ls`
- [ ] `.env` 备份路径已记入变更单

---

## 3. 生产密钥与环境变量

编辑 **`/opt/sem-backend/.env`**（`geo-service` 与 `sem-backend` **共用**该文件，见 unit `EnvironmentFile=`）。

### 3.1 必改项

| 变量 | 要求 |
| --- | --- |
| `APP_ENV` | `prod` 或 `production` |
| `APP_BASE_URL` | 公网 HTTPS，如 `https://gsniper.snipers.com.cn`（**禁止** localhost） |
| `ADMIN_API_KEY` | 强随机；**禁止** `geo-demo-local-key` / `CHANGE_ME` |
| `JWT_SECRET` | 强随机，且 **≠** `ADMIN_API_KEY` |
| `CRYPTO_MASTER_KEY_B64` | 标准 Base64，解码后 **恰好 32 字节** |
| `DATABASE_URL` | 生产库 `postgresql+asyncpg://...` |

生成示例（在服务器上，勿把结果贴进聊天/工单明文长期存放）：

```bash
# JWT / Admin key
openssl rand -hex 32

# CRYPTO_MASTER_KEY_B64（32 字节）
python3 -c "from base64 import b64encode; from os import urandom; print(b64encode(urandom(32)).decode())"
```

### 3.2 建议项

| 变量 | 说明 |
| --- | --- |
| `GEO_PATROL_MAX_RUNS_PER_DAY` | 默认 24；单租户自然日巡检启动上限 |
| `GEO_PATROL_MAX_CELLS_PER_RUN` | 默认 200；单次「词×引擎」格数上限 |
| `DASHSCOPE_API_KEY` / 租户 AI 配置 | 生产真采样；可走库内「AI 能力配置」 |
| `LOG_LEVEL` | 生产建议 `INFO` |

### 3.3 启动门禁说明

`APP_ENV=prod` 时，主站与 `geo_main` 启动会执行 `prod_guard`：

- demo / 空 / 占位密钥 → **进程拒绝启动**
- `JWT_SECRET` 空或与 `ADMIN_API_KEY` 相同 → **拒绝启动**

**勾选：**

- [ ] 已轮换三件套密钥  
- [ ] `APP_ENV=prod`  
- [ ] `APP_BASE_URL` 为公网 HTTPS  
- [ ] 文件权限：`chown sem:sem` 且 `chmod 600 /opt/sem-backend/.env`

---

## 4. 首次开通 GEO 独立单元（仅新环境）

若主机尚未做过 GEO 独立部署：

```bash
cd /path/to/ai_sni   # 发布用的代码树
sudo bash deploy/setup-geo.sh
```

效果：

- 目录：`/opt/geo-service`、`/opt/geo-frontend`、`/var/log/geo-service`
- 安装并 enable：`geo-service.service`（尚未有 release 时不要强求 active）

### 4.1 Nginx

将 `deploy/geo-routes.nginx.conf` **include** 进 HTTPS `server` 块，且位于通用 `/api/`、`/` **之前**。

**硬性禁止：**

```nginx
# 禁止出现类似配置
# proxy_set_header X-API-Key ...;
```

校验并重载：

```bash
sudo nginx -t && sudo systemctl reload nginx
```

**勾选：**

- [ ] `nginx -t` 通过  
- [ ] 配置中无 `X-API-Key` 注入  
- [ ] `/geo-health` 将转到 `127.0.0.1:8010/health/geo`

---

## 5. 数据库迁移

在**与生产相同 venv / 相同 DATABASE_URL** 的环境执行（建议在主站代码目录、`sem` 用户）：

```bash
cd /opt/sem-backend/current   # 或你们主站代码 current 路径
# 确认 .env 已指向生产库
set -a && source /opt/sem-backend/.env && set +a

# 看当前 revision
./.venv/bin/alembic current

# 升级到 head（含巡检表）
./.venv/bin/alembic upgrade head
./.venv/bin/alembic current
# 期望含 0053_patrol_window 或更新 head
```

**勾选：**

- [ ] `upgrade head` 无报错  
- [ ] 可选：`\d geo_visibility_patrol_runs` / `geo_visibility_patrol_settings` 存在  

若迁移失败：**不要**继续发版；用第 2 节 dump 评估回滚。

---

## 6. 发布 GEO API

在**有仓库克隆与 SSH 权限的发布机**：

```bash
export DEPLOY_TARGET=root@<生产主机>
# 可选：export GEO_API_ROOT=/opt/geo-service
bash scripts/deploy_geo_api.sh
```

脚本行为：

1. rsync `app/` + `migrations/` + `requirements.txt` + `alembic.ini` 到 `/opt/geo-service/releases/<stamp>`
2. 原子切换 `current`
3. `systemctl restart geo-service`
4. 探活：`/health/geo` 必须 `"db":"ok"`，否则回滚上一版本

机上手动探活：

```bash
systemctl is-active geo-service
curl -fsS http://127.0.0.1:8010/health/geo
# {"service":"geo-api","env":"prod","db":"ok",...}

curl -fsS -H "X-API-Key: <生产ADMIN_API_KEY>" \
  http://127.0.0.1:8010/api/v1/geo/content-health
```

**勾选：**

- [ ] `geo-service` = `active`  
- [ ] `/health/geo` → `"db":"ok"` 且 `"env"` 为 prod  
- [ ] content-health 200  

---

## 7. 发布 GEO 静态前端 + 主站 Vue

### 7.1 独立 GEO 静态台

```bash
cd frontend/geo-frontend
# 按该目录 README / package.json 的 deploy 脚本
npm run deploy
```

探活：

```bash
curl -fsSI https://<公网域名>/deal-sniper/geo/dashboard.html
curl -fsS https://<公网域名>/geo-health
```

### 7.2 主站 Vue SPA

按主站既有流水线构建部署，并确认：

- 生产构建 **未** 设置 `VITE_API_KEY`（登录走 JWT）
- 菜单可进：`/geo/overview`、`/geo/tasks`、`/geo/visibility`、`/geo/visibility/patrol`、`/geo/publishing`

**勾选：**

- [ ] 公网 dashboard / geo-health 200  
- [ ] 未登录访问业务 API 不因 Nginx 被「变成超管」  

---

## 8. 主站 sem-backend（调度与登录）

定时可见度巡检跑在 **GEO scheduler**（`app/geo/content/geo_scheduler.py`，约每小时 :05）。主站 `app.main` 与独立 `geo_main` 都会尝试启动，跨进程锁保证只跑一份。

```bash
# 发布/重启主站后
systemctl is-active sem-backend
journalctl -u sem-backend -n 50 --no-pager | grep -E 'scheduler|prod_guard|启动'

# 确认调度已注册（日志中有 geo_visibility_patrols 或「已启动」）
```

若仅更新了 geo-service 而未重启主站：巡检 API 可用，但**定时任务仍依赖旧主站进程**——主站代码含巡检调度时需一并发布并重启 `sem-backend`。

**勾选：**

- [ ] `sem-backend` active
- [ ] 启动日志无 `prod_guard` 失败  
- [ ] 调度已启动  

---

## 9. 机上验收清单（签字用）

### 9.1 基础设施

| # | 命令/动作 | 期望 | 结果 |
| --- | --- | --- | --- |
| H1 | `systemctl is-active geo-service` | active | ☐ |
| H2 | `curl -fsS http://127.0.0.1:8010/health/geo` | 200 + `"db":"ok"` | ☐ |
| H3 | `curl -fsS https://<host>/geo-health` | 与 H2 一致 | ☐ |
| H4 | `systemctl is-active sem-backend` | active | ☐ |
| H5 | `grep -R "X-API-Key" /etc/nginx/`（或站点 conf） | **无** proxy 注入 | ☐ |
| H6 | `journalctl -u geo-service -n 20` | 有近期日志 | ☐ |

### 9.2 业务抽测（浏览器，普通账号登录）

| # | 步骤 | 期望 | 结果 |
| --- | --- | --- | --- |
| B1 | 登录主站 | JWT 会话，无依赖本地 demo key | ☐ |
| B2 | `/geo/overview` | 无白屏，KPI 有数或 0 | ☐ |
| B3 | `/geo/tasks` 打开任务 → 渠道/审校或回填 | 门禁错误明确（非静默） | ☐ |
| B4 | `/geo/publishing` 官网 Webhook 账号 | 凭证已配置时显示就绪；错误有文案 | ☐ |
| B5 | 任务 Webhook 推送或公网 URL 回填 | 成功或业务 4xx 提示 | ☐ |
| B6 | `/geo/visibility/patrol` 立即巡检（小 limit） | 进入 running→completed；可落库 | ☐ |
| B7 | 保存定时：时段 + 间隔 | 刷新后仍在；说明主站 scheduler 在跑 | ☐ |

### 9.3 可选：带生产 Key 的脚本探活

```bash
# 在可访问 8010 的机器上（慎用生产 Key）
export KEY='<ADMIN_API_KEY>'
export BASE='http://127.0.0.1:8010'

curl -fsS -H "X-API-Key: $KEY" "$BASE/api/v1/geo/content-health"
curl -fsS -H "X-API-Key: $KEY" \
  "$BASE/api/v1/geo/visibility-patrol/settings?tenant_id=1"
```

---

## 10. 备份与日志（上线后常态）

| 项 | 建议 |
| --- | --- |
| Postgres | 每日 `pg_dump`；保留 7 日 + 4 周；迁移后再打一份 |
| `.env` | 仅密钥保管系统 / 加密盘；权限 600 |
| 日志 | `journalctl -u geo-service` / `sem-backend`；Nginx `sem-access.log` / `sem-error.log` |
| 巡检成本 | 观察 `GEO_PATROL_*` 与 DashScope 账单；必要时下调日配额 |

---

## 11. 回滚

### 11.1 仅回滚 GEO API

```bash
ls /opt/geo-service/releases
sudo ln -sfn /opt/geo-service/releases/<上一stamp> /opt/geo-service/current
sudo systemctl restart geo-service
curl -fsS http://127.0.0.1:8010/health/geo
```

### 11.2 迁移回滚（谨慎）

```bash
# 仅当确认 down_revision 安全且业务允许
./.venv/bin/alembic downgrade <上一revision>
# 或从第 2 节 dump 恢复整库（需停写）
```

### 11.3 密钥误配导致无法启动

1. 临时将 `APP_ENV=dev` **仅用于**紧急排查（不推荐长时间）  
2. 或修正 `JWT_SECRET` / `ADMIN_API_KEY` / `CRYPTO_*` 后 `systemctl restart geo-service sem-backend`  
3. 查看：`journalctl -u geo-service -n 100 | grep prod_guard`

---

## 12. 签字

| 角色 | 姓名 | 日期 | 结论 |
| --- | --- | --- | --- |
| 运维 | | | H1–H6 通过；备份已做 |
| 研发 | | | 迁移 + 发布 + B6/B7 通过 |
| 产品/交付 | | | B1–B5 主环可演示 |

**发布说明模板：**

```text
GEO 生产第三步：APP_ENV=prod，密钥已轮换；alembic head；
geo-service /health/geo db=ok；Nginx 无 API Key 注入；
主站 scheduler 负责可见度定时巡检；静态 /deal-sniper/geo + Vue /geo/*。
```

---

## 13. 相关文件索引

| 路径 | 用途 |
| --- | --- |
| `deploy/setup-geo.sh` | 首次目录 + systemd |
| `deploy/geo-service.service` | GEO 进程定义（8010，共用 `.env`） |
| `deploy/geo-routes.nginx.conf` | GEO 路由片段 |
| `scripts/deploy_geo_api.sh` | API 发布 + 探活回滚 |
| `app/security/prod_guard.py` | 生产密钥硬门禁 |
| `docs/GEO_DELIVERY_CHECKLIST.md` | 交付总清单 |
| `deploy/README-GEO-INDEPENDENT.md` | 独立发布单元说明 |

# GEO independent release unit

> **真实服务器上线完整步骤（中文 runbook）：**  
> [`docs/GEO_PRODUCTION_RUNBOOK.md`](../docs/GEO_PRODUCTION_RUNBOOK.md)  
> （备份 → 密钥 → 迁移 → 发布 → 探活 → 业务抽测 → 回滚 → 签字）

Production keeps the existing public URLs but routes GEO before the shared SEM
application:

- `/deal-sniper/geo/*` → `/opt/geo-frontend/current`
- `/api/v1/geo/*` → `geo-service.service` on `127.0.0.1:8010`
- `/geo-health` → the GEO service health endpoint

The GEO API process mounts only `app.geo.routes`, starts its own GEO scheduler,
and never starts or restarts the SEM scheduler/service.

## First-time server setup

1. Install `deploy/geo-service.service` in `/etc/systemd/system/`.
2. Create `/var/log/geo-service` owned by `sem:sem`.
3. Include `deploy/geo-routes.nginx.conf` inside the HTTPS
   `server_name sem.snipers.com.cn` block, before the general `/api/` and `/`
   locations.
4. Run `nginx -t`, reload Nginx, then enable `geo-service`.

## Releases

```bash
cd frontend/geo-frontend && npm run deploy
scripts/deploy_geo_api.sh
```

Both frontend and API use timestamped releases and an atomic `current` symlink.
Frontend rollback only changes `/opt/geo-frontend/current`. API rollback changes
`/opt/geo-service/current` and restarts only `geo-service`.

Database configuration and authentication tables remain shared with the main
platform. Schema migrations are intentionally not run by the GEO deploy script;
they must be reviewed separately because a database migration can affect shared
data even when processes are isolated.

## Host bootstrap

```bash
sudo bash deploy/setup-geo.sh
```

Creates `/opt/geo-service`, `/opt/geo-frontend`, `/var/log/geo-service`, installs
`geo-service.service` and enables it (does not start until first deploy + `.env`).

## Production acceptance checklist

| Check | Expect |
| --- | --- |
| `systemctl is-active geo-service` | `active` |
| `curl -fsS http://127.0.0.1:8010/health/geo` | HTTP **200** and `"db":"ok"` (DB down → **503**) |
| `curl -fsS http://127.0.0.1:8010/api/v1/geo/content-health` | `{"module":"geo-content","status":"ok"}` (needs auth if locked; public health is `/health/geo`) |
| `curl -fsS https://<host>/geo-health` | proxies to GEO health |
| `curl -fsSI https://<host>/deal-sniper/geo/` | 200 |
| `systemctl is-active sem-backend` | unchanged by GEO deploy |

Rollback API:

```bash
# list releases, re-point current, restart only geo-service
ls /opt/geo-service/releases
ln -sfn /opt/geo-service/releases/<stamp> /opt/geo-service/current
systemctl restart geo-service
```

Deploy smoke (`scripts/deploy_geo_api.sh`) asserts `/health/geo` body contains
`"db":"ok"` and probes `content-health`; on failure it restores the previous
`current` symlink and restarts `geo-service`.

## Production secrets (must-do)

Before setting `APP_ENV=prod` or `production` on the server:

| Variable | Rule |
| --- | --- |
| `ADMIN_API_KEY` | Not `geo-demo-local-key` / `CHANGE_ME` / empty |
| `JWT_SECRET` | Set, **≠** `ADMIN_API_KEY` |
| `CRYPTO_MASTER_KEY_B64` | Valid base64 of **32** bytes (see `.env.example`) |
| `APP_BASE_URL` | Public HTTPS host (not localhost) |

Startup runs `app.security.prod_guard.enforce_production_secrets` and **aborts** if
any rule fails. Nginx must **not** inject `X-API-Key` (see comments in
`deploy/nginx.conf` and `deploy/geo-routes.nginx.conf`). Production frontend
build must not embed `VITE_API_KEY` — users log in with JWT.

## Logs & backup (ops)

| Path | Purpose |
| --- | --- |
| `/var/log/geo-service/` | GEO API journal (unit `StandardOutput` / files if configured) |
| `journalctl -u geo-service -f` | Live GEO logs |
| `journalctl -u sem-backend -f` | Main API + scheduler (incl. visibility patrol cron) |
| `/var/log/nginx/sem-access.log` / `sem-error.log` | Edge access / errors |
| PostgreSQL | Shared DB — use existing platform backup (pg_dump / snapshot); **schema migrations are not auto-run by GEO deploy** |

Recommended backup cadence (document on the customer runbook):

1. Daily logical dump of Postgres (tenants, geo_* tables, auth).
2. Keep last 7 daily + 4 weekly dumps off-box.
3. After `alembic upgrade head`, take an extra dump before restarting services.

## Productization verify (local / CI helper)

```bash
# code + nginx + prod_guard + optional live API
python scripts/verify_productization_must.py
python scripts/verify_productization_must.py http://127.0.0.1:8011 geo-demo-local-key 1
```

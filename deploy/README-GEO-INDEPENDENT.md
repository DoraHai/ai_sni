# GEO independent release unit

Production keeps the existing public URLs but routes GEO before the shared SEM
application:

- `/deal-sniper/geo/*` → `/opt/geo-frontend/current`
- `/api/v1/geo/*` → `geo-service.service` on `127.0.0.1:8010`
- `/geo-health` → the GEO service health endpoint

The GEO API process mounts only `app.api.geo`. It does not start the SEM
scheduler and a GEO release does not restart `sem-backend.service`.

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
| `curl -fsSI https://<host>/deal-sniper/geo/dashboard.html` | 200 |
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

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

# GEO independent deployment unit

This unit builds and deploys GEO without replacing the SEM frontend.

## Boundaries

- Canonical pages: `../public/deal-sniper-prototype/geo`
- Local build output: `dist`
- Production releases: `/opt/geo-frontend/releases/<timestamp>`
- Active production release: `/opt/geo-frontend/current`
- Public path: `/deal-sniper/geo/*`

## Commands

```bash
npm run dev
npm run build
npm run deploy
```

Deployments switch the `current` symlink atomically. To roll back, repoint it to
an earlier timestamped release. No SEM frontend directory is replaced and no
SEM process is restarted.

The production Nginx configuration serves this unit before the SEM SPA route,
so existing links remain valid.

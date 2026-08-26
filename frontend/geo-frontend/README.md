# GEO independent deployment unit

This unit builds and deploys GEO without replacing the SEM frontend.

## Boundaries

- Canonical app: standalone Vue shell in `src/`, reusing `../src/views/geo/**`
- Local build output: `dist`
- Production releases: `/opt/geo-frontend/releases/<timestamp>`
- Active production release: `/opt/geo-frontend/current`
- Public entry: `/deal-sniper/geo/#/geo/overview`
- Compatibility entry: `/deal-sniper/geo/dashboard.html`

## Commands

```bash
npm run dev
npm run build
npm run deploy
```

Deployments switch the `current` symlink atomically. To roll back, repoint it to
an earlier timestamped release. No SEM frontend directory is replaced and no
SEM process is restarted.

The production Nginx configuration serves this unit before the SEM SPA route.
Its router uses hash history, so every GEO page stays inside this independently
deployed frontend without adding GEO routes or menus back to the SEM SPA.

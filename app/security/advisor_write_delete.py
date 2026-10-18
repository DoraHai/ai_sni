"""Only reviewed object deletes; no tenant-wide cleanup or configuration deletes."""
PATHS = frozenset({"/api/v1/geo/content-tasks/{task_id}",
                   "/api/v1/geo/answer-snapshots/{snapshot_id}"})


def rules():
    from app.security.advisor_write_routes import FORBIDDEN, WriteRule
    return {("DELETE", path): WriteRule("DELETE", path, frozenset(), FORBIDDEN,
             ("geo.assets", "geo.content"), "project") for path in PATHS}

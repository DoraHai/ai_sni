"""Legacy configuration GETs expose defaults without creating database rows."""

import asyncio

from app.geo.content import routes
from app.geo.read_session import geo_read_session
from app.geo.tenant_scope import require_geo_read_entitlement


class EmptyReadSession:
    async def scalars(self, _statement):
        return []


def _route(path):
    return next(
        route
        for route in routes.router.routes
        if route.path == path and route.methods == {"GET"}
    )


def test_default_configuration_gets_use_read_only_session_and_entitlement():
    paths = {
        "/publishing-channel-options",
        "/publishing-channels",
        "/publishing-channels/auto-push-status",
        "/tracking-engines",
        "/monitoring-stance",
        "/media-placements",
        "/channel-blueprint",
        "/content-tasks/{task_id}",
    }
    for path in paths:
        route = _route(path)
        calls = {dependency.call for dependency in route.dependant.dependencies}
        assert route.methods == {"GET"}
        assert geo_read_session in calls, path
        assert require_geo_read_entitlement in calls, path


def test_empty_configuration_returns_transient_defaults_without_write_methods():
    async def run():
        session = EmptyReadSession()
        channels = await routes._publishing_channel_view_rows(session, 7)
        engines = await routes._tracking_engine_view_rows(session, 7)
        placements = await routes._media_placement_view_rows(session, 7)

        assert channels and all(row.tenant_id == 7 and row.id is None for row in channels)
        assert engines and all(row.tenant_id == 7 and row.id is None for row in engines)
        assert placements and all(row.tenant_id == 7 and row.id is None for row in placements)
        options = await routes._channel_options_payload(session, 7)
        assert options and all(item["publishing_channel_id"] is None for item in options)

    asyncio.run(run())

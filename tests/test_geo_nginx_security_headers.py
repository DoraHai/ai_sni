from pathlib import Path


ROOT = Path(__file__).parents[1]
BASELINE_HEADERS = (
    'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;',
    'add_header X-Content-Type-Options "nosniff" always;',
    'add_header Referrer-Policy "strict-origin-when-cross-origin" always;',
    'add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;',
)


def _location_block(config: str, marker: str) -> str:
    start = config.index(marker)
    brace = config.index("{", start)
    depth = 0
    for index in range(brace, len(config)):
        if config[index] == "{":
            depth += 1
        elif config[index] == "}":
            depth -= 1
            if depth == 0:
                return config[start : index + 1]
    raise AssertionError(f"unterminated nginx location: {marker}")


def test_geo_and_diagnostic_cache_locations_repeat_security_headers():
    config = (ROOT / "deploy/geo-routes.nginx.conf").read_text(encoding="utf-8")
    for marker in (
        "location = /diagnostic-center/index.html",
        "location ^~ /diagnostic-center/assets/",
        "location ^~ /deal-sniper/geo/assets/",
        "location ^~ /deal-sniper/geo/ {",
    ):
        block = _location_block(config, marker)
        for header in BASELINE_HEADERS:
            assert header in block

    for marker in (
        "location = /diagnostic-center/index.html",
        "location ^~ /deal-sniper/geo/ {",
    ):
        block = _location_block(config, marker)
        assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in block
        assert "frame-ancestors 'self'" in block
        assert 'add_header X-Frame-Options "DENY"' not in block

from pathlib import Path


ROOT = Path(__file__).parents[1]
BASELINE_HEADERS = (
    'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;',
    'add_header X-Content-Type-Options "nosniff" always;',
    'add_header Referrer-Policy "strict-origin-when-cross-origin" always;',
    'add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;',
)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


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


def _assert_baseline(block: str) -> None:
    for header in BASELINE_HEADERS:
        assert header in block


def _assert_same_origin_frame_policy(block: str) -> None:
    assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in block
    assert "frame-ancestors 'self'" in block
    assert 'add_header X-Frame-Options "DENY"' not in block


def test_geo_and_diagnostic_locations_keep_security_headers_with_cache_headers():
    config = _read("deploy/geo-routes.nginx.conf")
    markers = (
        "location = /diagnostic-center/index.html",
        "location ^~ /diagnostic-center/assets/",
        "location ^~ /deal-sniper/geo/assets/",
        "location ^~ /deal-sniper/geo/ {",
    )
    for marker in markers:
        _assert_baseline(_location_block(config, marker))

    _assert_same_origin_frame_policy(
        _location_block(config, "location = /diagnostic-center/index.html")
    )
    _assert_same_origin_frame_policy(
        _location_block(config, "location ^~ /deal-sniper/geo/ {")
    )


def test_seo_locations_keep_security_headers_with_cache_headers():
    config = _read("deploy/seo-frontend.nginx.conf")
    markers = (
        "location ^~ /seo/assets/",
        "location = /seo/index.html",
        "location /seo/",
    )
    for marker in markers:
        _assert_baseline(_location_block(config, marker))

    _assert_same_origin_frame_policy(
        _location_block(config, "location = /seo/index.html")
    )
    _assert_same_origin_frame_policy(_location_block(config, "location /seo/"))

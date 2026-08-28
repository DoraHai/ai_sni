"""Safety checks for the restricted SEM frontend deployment boundary."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _nginx_location_block(config: str, marker: str) -> str:
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


def test_sem_frontend_deploy_uses_unprivileged_account_and_readable_modes():
    script = _read("frontend/scripts/deploy-sem.sh")

    assert "sem-deploy@101.200.193.83" in script
    assert "root@101.200.193.83" not in script
    assert "chown" not in script
    assert "--chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r" in script
    assert "StrictHostKeyChecking=yes" in script


def test_sem_ci_uses_pinned_host_key_and_dedicated_secret():
    workflow = _read(".github/workflows/ci.yml")

    assert "SEM_DEPLOY_SSH_KEY" in workflow
    assert "DEPLOY_KNOWN_HOSTS" in workflow
    assert "ssh-keyscan" not in workflow
    assert "DEPLOY_TARGET: sem-deploy@101.200.193.83" in workflow
    assert "environment: production" in workflow


def test_canonical_domain_and_portal_routes_are_release_contracts():
    nginx = _read("deploy/gsnipers.conf")
    build_guard = _read("frontend/scripts/verify-sem-build.mjs")
    seo_shell = _read("frontend/src/views/seo/SeoWorkspaceShell.vue")

    assert "server_name gsnipers.snipers.com.cn;" in nginx
    assert "server_name gsniper.snipers.com.cn;" not in nginx
    assert "location ^~ /deal-sniper-prototype/" in nginx
    assert "location ~ ^/(deal-sniper|diagnosis)(/|$)" in nginx
    assert "'/deal-sniper/portal'" in build_guard
    assert "'/deal-sniper-prototype/index.html'" in build_guard
    assert "'gsnipers.snipers.com.cn'" in build_guard
    assert "'https://gsniper.snipers.com.cn'" in build_guard
    assert "href=\"/deal-sniper/portal\"" in seo_shell
    assert "https://gsnipers.snipers.com.cn/deal-sniper/portal" not in seo_shell


def test_sem_nginx_security_headers_cover_api_spa_and_portal_iframe():
    nginx = _read("deploy/gsnipers.conf")
    https_server = nginx[nginx.index("listen 443 ssl http2;") :]
    server_headers = https_server[: https_server.index("\n    location ")]
    baseline = (
        'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;',
        'add_header X-Content-Type-Options "nosniff" always;',
        'add_header Referrer-Policy "strict-origin-when-cross-origin" always;',
        'add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;',
    )
    for header in baseline:
        assert header in server_headers

    prototype = _nginx_location_block(nginx, "location ^~ /deal-sniper-prototype/")
    sem_routes = _nginx_location_block(
        nginx,
        "location ~ ^/(deal-sniper|diagnosis)(/|$)",
    )
    for header in baseline:
        assert header in prototype
        assert header in sem_routes
    assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in prototype
    assert "frame-ancestors 'self'" in prototype
    assert 'add_header X-Frame-Options "DENY" always;' in sem_routes
    assert "frame-ancestors 'none'" in sem_routes

"""Exercise the actual Nginx index module, without touching a system server."""
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("nginx"), reason="real Nginx is required")
def test_workbench_directory_index_assets_query_and_unknown_path(tmp_path):
    source = (Path(__file__).parents[1] / "deploy/gsnipers-platform-routes.conf").read_text()
    locations = source[source.index("    # Independent customer workbench;"):source.index("    # The SEM HTML shell")]
    site = tmp_path / "site"
    site.mkdir()
    for name in ("index.html", "app.js", "app.css"):
        (site / name).write_text("fixture:" + name)
    locations = locations.replace("/opt/customer-workbench/current", str(site))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = tmp_path / "nginx.conf"
    config.write_text(
        f"pid {tmp_path}/nginx.pid; error_log {tmp_path}/error.log; "
        "daemon off; master_process off; events {} http { access_log off; "
        f"server {{ listen 127.0.0.1:{port}; index index.html; {locations} }} }}"
    )
    process = subprocess.Popen([shutil.which("nginx"), "-p", str(tmp_path), "-c", str(config)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    origin = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            if process.poll() is not None:
                pytest.fail(process.stderr.read().decode())
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    break
            except OSError:
                time.sleep(.05)
        for path, expected in (
            ("/customer-workbench/", "index.html"),
            ("/customer-workbench/?tenant_id=1&site_id=1", "index.html"),
            ("/customer-workbench?tenant_id=1&site_id=1", "index.html"),
            ("/customer-workbench/app.js", "app.js"),
            ("/customer-workbench/app.css", "app.css"),
        ):
            with urllib.request.urlopen(origin + path, timeout=3) as response:
                assert response.status == 200
                assert response.read() == ("fixture:" + expected).encode()
                if "?" in path:
                    assert response.url.endswith("?tenant_id=1&site_id=1")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(origin + "/customer-workbench/release-manifest.json", timeout=3)
        assert error.value.code == 404
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

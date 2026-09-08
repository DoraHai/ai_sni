from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

if os.name != "nt":
    import grp
    import pwd


ROOT = Path(__file__).parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def block(config: str, declaration: str) -> str:
    start = config.index(declaration)
    brace = config.index("{", start)
    depth = 0
    for index in range(brace, len(config)):
        if config[index] == "{":
            depth += 1
        elif config[index] == "}":
            depth -= 1
            if depth == 0:
                return config[start : index + 1]
    raise AssertionError(f"unterminated Nginx block: {declaration}")


def test_candidate_is_exact_reviewed_base_plus_one_narrow_spa_location():
    base = read("tests/fixtures/gsnipers-platform-routes-reviewed-base.conf")
    candidate = read("deploy/gsnipers-platform-routes.conf")
    marker = "    # Only declared business routes enter the SEM SPA."
    added = candidate[len(base[: base.index(marker)]) : candidate.index(marker)]
    assert candidate == base.replace(marker, added + marker, 1)
    assert "location ~ ^/platform(/|$)" in added
    assert "location = /admin/internal" not in added
    assert added.count("location ") == 1
    assert hashlib.sha256(base.encode()).hexdigest() == "3fd57506ca30704d5201d15ac9ab2408bda951f1b8fd0c4118c47d7023506fc1"
    assert hashlib.sha256(candidate.encode()).hexdigest() == "d710448c24f61e14c0e69a5c2636987781b09042a3a72cd7a11605d316ad12f3"


def test_platform_serves_sem_index_and_preserves_legacy_admin_redirect():
    config = read("deploy/gsnipers-platform-routes.conf")
    platform = block(config, "location ~ ^/platform(/|$)")
    legacy = block(config, "location = /admin/internal")
    assert "root /opt/sem-frontend/current;" in platform
    assert "/sem-index.html" in platform
    assert 'add_header X-Frame-Options "DENY" always;' in platform
    assert "frame-ancestors 'none'" in platform
    assert 'add_header X-Content-Type-Options "nosniff" always;' in platform
    assert "return 308 /settings/accounts;" in legacy
    assert config.count("location = /admin/internal") == 1
    assert config.index("location ^~ /api/v1/") < config.index("location ~ ^/platform(/|$)")
    for unchanged in (
        "include /etc/nginx/snippets/diagnostic-api.conf;",
        "include /etc/nginx/snippets/geo-routes.conf;",
        "include /etc/nginx/snippets/seo-frontend.conf;",
        "location ^~ /assets/",
        "location ~ ^/(assistant|onboarding|monitor|optimize|verify|manage|delivery|settings|workspace|sem)(/|$)",
    ):
        assert unchanged in config


def test_release_module_validates_before_reload_and_has_complete_rollback():
    script = read("ops/platform-deploy/modules/platform")
    mutation = script.index('mv -Tf "${target}.next" "$target"')
    validation = script.index("nginx -t", mutation)
    activation = script.index("systemctl reload nginx", validation)
    smoke = script.index("/platform/customers", activation)
    assert mutation < validation < activation < smoke
    assert "for attempt in {1..10}" in script
    assert '[[ "$attempt" -eq 10 ]] || sleep 1' in script
    restore = script[script.index("restore() {") : script.index("mapfile -t archive_entries")]
    assert 'mv -Tf "${target}.rollback" "$target"' in restore
    assert "nginx -t" in restore and "systemctl reload nginx" in restore
    assert 'if [[ "$started" == true && "$committed" != true ]]' in script
    assert 'status=70' in script
    assert "(^/|(^|/)\\.\\.(/|$))" in script
    assert "*) return 1" in script
    assert "already_current=true" in script
    assert 'git ls-remote --refs "$authoritative_repo" "$authoritative_ref"' in script
    assert "authoritative_query_attempts=3" in script
    assert "authoritative_retry_delay_seconds=2" in script
    assert '[[ "$attempt" -eq "$authoritative_query_attempts" ]] || sleep "$authoritative_retry_delay_seconds"' in script
    assert script.count('live_head="$(query_authoritative_head)"') == 2
    assert script.index("flock -n 9") < script.index('live_head="$(query_authoritative_head)"')
    assert script.rindex('live_head="$(query_authoritative_head)"') < script.index('mv -Tf "$archive" "$published_archive"')
    assert script.index('expected_index="${PLATFORM_SEM_INDEX:-/opt/sem-frontend/current/index.html}"') < script.index("status=already-current")
    for route in (
        "/platform/customers",
        "/platform/accounts",
        "/platform/roles",
        "/settings/customers",
        "/settings/accounts",
        "/settings/users",
        "/admin/internal",
        "/workspace/cockpit",
        "/monitor/dashboard",
        "/optimize/keywords",
    ):
        assert route in script
    assert "migration=not-run" in script


def test_installer_and_workflow_are_exact_revision_and_prewrite_gated():
    installer = read("ops/platform-deploy/install-platform-routes.sh")
    publisher = read("ops/platform-deploy/publish-platform-routes.sh")
    workflow = read(".github/workflows/production-sem-platform-routes.yml")
    digest_gate = installer.index("reviewed_dispatcher_sha256")
    first_install = installer.index("install -d")
    assert digest_gate < first_install
    assert "0330e2c14f2ff7074df140e02d56136aa2a5248ebce296d9c35007437c09937a" in installer
    module_bytes = (ROOT / "ops/platform-deploy/modules/platform").read_bytes().replace(b"\r\n", b"\n")
    module_digest = hashlib.sha256(module_bytes).hexdigest()
    assert module_digest == "c8824ba23eb0efdd57f9c6a0027685f3d2da7a99d39a09cef54d8e639493639d"
    assert module_digest in installer
    assert 'sha256sum "$source_module"' in installer
    assert "platform=enabled" in installer
    assert "platform route installer rollback failed" in installer
    assert 'if [[ "$committed" != true ]]' in installer
    assert "github.event.pull_request.head.sha || github.sha" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "environment: production" in workflow
    assert 'ops/platform-deploy/publish-platform-routes.sh "$archive" "${{ github.sha }}" "$digest"' in workflow
    assert publisher.count("require_current_head") >= 3
    assert "mv '$remote_part' '$remote'" not in publisher
    assert "platform-deploy apply platform '$remote_part'" in publisher
    assert "migration=not-run" in workflow


def _write_command(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _release_fixture(tmp_path: Path, fail_at: str = "", curl_mode: str = "fail"):
    base = (ROOT / "tests/fixtures/gsnipers-platform-routes-reviewed-base.conf").read_bytes()
    candidate = (ROOT / "deploy/gsnipers-platform-routes.conf").read_bytes()
    upload = tmp_path / "uploads"
    upload.mkdir()
    commit = "a" * 40
    archive = upload / f"platform-routes-{commit}.tgz.part-123-1"
    manifest = (
        "module=platform-routes\n"
        f"commit={commit}\n"
        "migration=not-run\n"
        "frontend=not-included\n"
        "backend=not-included\n"
    ).encode()
    with tarfile.open(archive, "w:gz") as tar:
        root = tarfile.TarInfo("platform-routes-release/")
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        tar.addfile(root)
        for name, payload in (("gsnipers.conf", candidate), ("MANIFEST", manifest)):
            info = tarfile.TarInfo(f"platform-routes-release/{name}")
            info.size = len(payload)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(payload))

    target = tmp_path / "gsnipers.conf"
    target.write_bytes(base)
    expected_index = tmp_path / "index.html"
    expected_index.write_text("reviewed SEM index", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls"
    state = tmp_path / "command-state"
    state.mkdir()
    for name in ("install", "mv"):
        real = shutil.which(name)
        assert real
        _write_command(
            fake_bin / name,
            f'''name={name!r}
count_file="$PLATFORM_TEST_STATE/$name"
count=0
[[ ! -f "$count_file" ]] || count="$(cat "$count_file")"
count=$((count + 1))
printf '%s' "$count" > "$count_file"
printf '%s %s\\n' "$name" "$*" >> "$PLATFORM_TEST_CALLS"
[[ "$PLATFORM_TEST_FAIL" != "$name:$count" ]] || exit 97
exec {real!r} "$@"
''',
        )
    for name in ("nginx", "systemctl", "sleep"):
        _write_command(
            fake_bin / name,
            f'''name={name!r}
count_file="$PLATFORM_TEST_STATE/$name"
count=0
[[ ! -f "$count_file" ]] || count="$(cat "$count_file")"
count=$((count + 1))
printf '%s' "$count" > "$count_file"
printf '%s %s\\n' "$name" "$*" >> "$PLATFORM_TEST_CALLS"
[[ "$PLATFORM_TEST_FAIL" != "$name:$count" ]] || exit 97
''',
        )
    _write_command(
        fake_bin / "curl",
        '''count_file="$PLATFORM_TEST_STATE/curl"
count=0
[[ ! -f "$count_file" ]] || count="$(cat "$count_file")"
count=$((count + 1))
printf '%s' "$count" > "$count_file"
printf 'curl %s\\n' "$*" >> "$PLATFORM_TEST_CALLS"
[[ "$PLATFORM_TEST_CURL_MODE" != fail ]] || exit 22
[[ "$PLATFORM_TEST_CURL_MODE" != transient || "$count" -ne 1 ]] || exit 22
output=''
headers=''
url=''
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    -o) shift; output="$1" ;;
    -D) shift; headers="$1" ;;
    http*) url="$1" ;;
  esac
  shift
done
if [[ "$url" == */admin/internal ]]; then
  printf 'HTTP/2 308\\r\\nLocation: /settings/accounts\\r\\n\\r\\n' > "$headers"
  printf '308'
elif [[ -n "$output" ]]; then
  cp "$PLATFORM_SEM_INDEX" "$output"
fi
''',
    )
    _write_command(
        fake_bin / "git",
        f'printf \'git %s\\n\' "$*" >> "$PLATFORM_TEST_CALLS"\nprintf \'{commit}\\trefs/heads/codex/production-sem\\n\'\n',
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "PLATFORM_DEPLOY_UPLOAD_ROOT": str(upload),
            "PLATFORM_NGINX_TARGET": str(target),
            "PLATFORM_NGINX_BACKUP_ROOT": str(tmp_path / "backups"),
            "PLATFORM_NGINX_LOCK_FILE": str(tmp_path / "deploy.lock"),
            "PLATFORM_DEPLOY_ARCHIVE_OWNER": pwd.getpwuid(os.getuid()).pw_name,
            "PLATFORM_NGINX_OWNER": pwd.getpwuid(os.getuid()).pw_name,
            "PLATFORM_NGINX_GROUP": grp.getgrgid(os.getgid()).gr_name,
            "PLATFORM_DEPLOY_TMP_ROOT": str(tmp_path),
            "PLATFORM_SEM_INDEX": str(expected_index),
            "PLATFORM_TEST_CALLS": str(calls),
            "PLATFORM_TEST_STATE": str(state),
            "PLATFORM_TEST_FAIL": fail_at,
            "PLATFORM_TEST_CURL_MODE": curl_mode,
        }
    )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return base, target, calls, archive, commit, digest, env


def _set_git_response_sequence(env: dict[str, str], responses: list[str], commit: str) -> None:
    fake_bin = Path(env["PATH"].split(":", 1)[0])
    response_file = Path(env["PLATFORM_TEST_STATE"]) / "git-responses"
    response_file.write_text("\n".join(responses) + "\n", encoding="utf-8")
    env["PLATFORM_TEST_GIT_RESPONSES"] = str(response_file)
    env["PLATFORM_TEST_COMMIT"] = commit
    _write_command(
        fake_bin / "git",
        '''response="$(head -n 1 "$PLATFORM_TEST_GIT_RESPONSES")"
tail -n +2 "$PLATFORM_TEST_GIT_RESPONSES" > "$PLATFORM_TEST_GIT_RESPONSES.next"
mv "$PLATFORM_TEST_GIT_RESPONSES.next" "$PLATFORM_TEST_GIT_RESPONSES"
printf 'git %s -> %s\n' "$*" "$response" >> "$PLATFORM_TEST_CALLS"
case "$response" in
  network) exit 128 ;;
  current) printf '%s\trefs/heads/codex/production-sem\n' "$PLATFORM_TEST_COMMIT" ;;
  newer) printf '%040d\trefs/heads/codex/production-sem\n' 0 ;;
  malformed) printf 'not-a-sha\trefs/heads/codex/production-sem\n' ;;
  multiple) printf '%s\trefs/heads/codex/production-sem\n%s\trefs/heads/codex/production-sem\n' "$PLATFORM_TEST_COMMIT" "$PLATFORM_TEST_COMMIT" ;;
  wrong_ref) printf '%s\trefs/heads/main\n' "$PLATFORM_TEST_COMMIT" ;;
  missing|'') exit 0 ;;
  *) exit 98 ;;
esac
''',
    )


@pytest.mark.skipif(os.name == "nt", reason="deployment state machine executes on Linux")
def test_release_module_executes_ordered_apply_and_complete_rollback(tmp_path: Path):
    base, target, calls, archive, commit, digest, env = _release_fixture(tmp_path)
    result = subprocess.run(
        ["bash", str(ROOT / "ops/platform-deploy/modules/platform"), str(archive), commit, digest, "DEPLOY_PLATFORM_ROUTES"],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert target.read_bytes() == base
    lines = calls.read_text(encoding="utf-8").splitlines()
    ordered = [
        "git ls-remote --refs ",
        "git ls-remote --refs ",
        "mv -Tf ",
        "install -d ",
        "install -o ",
        "mv -Tf ",
        "nginx -t",
        "systemctl reload nginx",
        "curl -fsS ",
        "install -o ",
        "mv -Tf ",
        "nginx -t",
        "systemctl reload nginx",
    ]
    cursor = 0
    for expected in ordered:
        cursor = next(i + 1 for i in range(cursor, len(lines)) if lines[i].startswith(expected))
    recorded = "\n".join(lines)
    assert recorded.count("nginx -t") == 2
    assert recorded.count("systemctl reload nginx") == 2


@pytest.mark.skipif(os.name == "nt", reason="deployment state machine executes on Linux")
@pytest.mark.parametrize(
    ("fail_at", "restored"),
    (("install:4", False), ("mv:3", False), ("nginx:2", True), ("systemctl:2", True)),
)
def test_release_module_reports_70_and_never_masks_rollback_stage_failure(tmp_path: Path, fail_at: str, restored: bool):
    base, target, calls, archive, commit, digest, env = _release_fixture(tmp_path, fail_at)
    result = subprocess.run(
        ["bash", str(ROOT / "ops/platform-deploy/modules/platform"), str(archive), commit, digest, "DEPLOY_PLATFORM_ROUTES"],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 70
    assert (target.read_bytes() == base) is restored
    assert "rollback failed" in result.stderr
    assert "active_sha256=" not in result.stdout
    lines = calls.read_text(encoding="utf-8").splitlines()
    if fail_at in {"install:4", "mv:3", "nginx:2"}:
        assert lines.count("systemctl reload nginx") == 1


@pytest.mark.skipif(os.name == "nt", reason="server publication boundary executes on Linux")
@pytest.mark.parametrize(
    "server_result",
    (
        "newer",
        "network_failure",
        "malformed",
        "multiple_refs",
        "ref_mismatch",
        "missing_ref",
        "boundary_drift",
    ),
)
def test_server_boundary_fails_closed_before_publish_or_active_mutation(tmp_path: Path, server_result: str):
    base, target, calls, archive, commit, digest, env = _release_fixture(tmp_path)
    git_command = Path(env["PATH"].split(":", 1)[0]) / "git"
    responses = {
        "newer": f"printf 'git %s\\n' \"$*\" >> \"$PLATFORM_TEST_CALLS\"\nprintf '{'b' * 40}\\trefs/heads/codex/production-sem\\n'\n",
        "network_failure": "printf 'git %s\\n' \"$*\" >> \"$PLATFORM_TEST_CALLS\"\nexit 128\n",
        "malformed": "printf 'git %s\\n' \"$*\" >> \"$PLATFORM_TEST_CALLS\"\nprintf 'not-a-sha\\trefs/heads/codex/production-sem\\n'\n",
        "multiple_refs": f"printf 'git %s\\n' \"$*\" >> \"$PLATFORM_TEST_CALLS\"\nprintf '{commit}\\trefs/heads/codex/production-sem\\n{commit}\\trefs/heads/codex/production-sem\\n'\n",
        "ref_mismatch": f"printf 'git %s\\n' \"$*\" >> \"$PLATFORM_TEST_CALLS\"\nprintf '{commit}\\trefs/heads/main\\n'\n",
        "missing_ref": "printf 'git %s\\n' \"$*\" >> \"$PLATFORM_TEST_CALLS\"\n",
        "boundary_drift": f'''count_file="$PLATFORM_TEST_STATE/git-boundary"
count=0
[[ ! -f "$count_file" ]] || count="$(cat "$count_file")"
count=$((count + 1))
printf '%s' "$count" > "$count_file"
printf 'git %s\\n' "$*" >> "$PLATFORM_TEST_CALLS"
if [[ "$count" -eq 1 ]]; then
  printf '{commit}\\trefs/heads/codex/production-sem\\n'
else
  printf '{'b' * 40}\\trefs/heads/codex/production-sem\\n'
fi
''',
    }
    _write_command(git_command, responses[server_result])
    result = subprocess.run(
        ["bash", str(ROOT / "ops/platform-deploy/modules/platform"), str(archive), commit, digest, "DEPLOY_PLATFORM_ROUTES"],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert not archive.exists()
    assert not (archive.parent / f"platform-routes-{commit}.tgz").exists()
    assert target.read_bytes() == base
    recorded = calls.read_text(encoding="utf-8")
    assert "git ls-remote --refs https://github.com/DoraHai/ai_sni.git refs/heads/codex/production-sem" in recorded
    assert "nginx " not in recorded
    assert "systemctl " not in recorded
    assert "curl " not in recorded
    assert "active_sha256=" not in result.stdout
    assert not any(line.startswith(f"mv -Tf {archive} ") for line in recorded.splitlines())
    expected_queries = 3 if server_result == "network_failure" else 2 if server_result == "boundary_drift" else 1
    assert recorded.count("git ls-remote --refs ") == expected_queries
    assert recorded.count("sleep 2") == (2 if server_result == "network_failure" else 0)


@pytest.mark.skipif(os.name == "nt", reason="server publication retry executes on Linux")
def test_server_boundary_retries_network_failures_then_uses_fresh_live_head(tmp_path: Path):
    _, target, calls, archive, commit, digest, env = _release_fixture(tmp_path, curl_mode="success")
    _set_git_response_sequence(env, ["network", "network", "current", "current"], commit)
    result = subprocess.run(
        ["bash", str(ROOT / "ops/platform-deploy/modules/platform"), str(archive), commit, digest, "DEPLOY_PLATFORM_ROUTES"],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert target.read_bytes() == (ROOT / "deploy/gsnipers-platform-routes.conf").read_bytes()
    recorded = calls.read_text(encoding="utf-8")
    assert recorded.count("git ls-remote --refs ") == 4
    assert recorded.count("sleep 2") == 2
    assert recorded.index("git ls-remote --refs ") < recorded.index("mv -Tf ")
    assert "active_sha256=" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="idempotent archive state machine executes on Linux")
def test_successful_deploy_same_commit_rerun_reuses_archive_and_only_smokes(tmp_path: Path):
    _, target, calls, inert, commit, digest, env = _release_fixture(tmp_path, curl_mode="success")
    command = ["bash", str(ROOT / "ops/platform-deploy/modules/platform"), str(inert), commit, digest, "DEPLOY_PLATFORM_ROUTES"]
    first = subprocess.run(command, env=env, text=True, capture_output=True)
    assert first.returncode == 0, first.stderr
    published = inert.parent / f"platform-routes-{commit}.tgz"
    published_inode = published.stat().st_ino
    shutil.copyfile(published, inert)
    calls.write_text("", encoding="utf-8")

    second = subprocess.run(command, env=env, text=True, capture_output=True)
    assert second.returncode == 0, second.stderr
    assert "status=already-current" in second.stdout
    assert not inert.exists()
    assert published.stat().st_ino == published_inode
    assert hashlib.sha256(published.read_bytes()).hexdigest() == digest
    second_calls = calls.read_text(encoding="utf-8")
    assert "nginx " not in second_calls
    assert "systemctl " not in second_calls
    assert "curl " in second_calls


@pytest.mark.skipif(os.name == "nt", reason="idempotent archive state machine executes on Linux")
def test_post_publish_failure_archive_is_reused_by_successful_same_commit_retry(tmp_path: Path):
    base, target, calls, inert, commit, digest, env = _release_fixture(tmp_path)
    command = ["bash", str(ROOT / "ops/platform-deploy/modules/platform"), str(inert), commit, digest, "DEPLOY_PLATFORM_ROUTES"]
    first = subprocess.run(command, env=env, text=True, capture_output=True)
    assert first.returncode != 0
    assert target.read_bytes() == base
    published = inert.parent / f"platform-routes-{commit}.tgz"
    published_inode = published.stat().st_ino
    shutil.copyfile(published, inert)
    env["PLATFORM_TEST_CURL_MODE"] = "success"
    calls.write_text("", encoding="utf-8")

    second = subprocess.run(command, env=env, text=True, capture_output=True)
    assert second.returncode == 0, second.stderr
    assert "active_sha256=" in second.stdout
    assert not inert.exists()
    assert published.stat().st_ino == published_inode
    assert target.read_bytes() == (ROOT / "deploy/gsnipers-platform-routes.conf").read_bytes()
    second_calls = calls.read_text(encoding="utf-8")
    assert second_calls.count("nginx -t") == 1
    assert second_calls.count("systemctl reload nginx") == 1


@pytest.mark.skipif(os.name == "nt", reason="nginx worker readiness executes on Linux")
def test_release_waits_for_new_nginx_worker_after_transient_404(tmp_path: Path):
    _, target, calls, inert, commit, digest, env = _release_fixture(tmp_path, curl_mode="transient")
    result = subprocess.run(
        ["bash", str(ROOT / "ops/platform-deploy/modules/platform"), str(inert), commit, digest, "DEPLOY_PLATFORM_ROUTES"],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert target.read_bytes() == (ROOT / "deploy/gsnipers-platform-routes.conf").read_bytes()
    recorded = calls.read_text(encoding="utf-8")
    assert recorded.count("curl ") == 13
    assert recorded.count("sleep 1") == 1


@pytest.mark.skipif(os.name == "nt", reason="published archive anomaly checks execute on Linux")
@pytest.mark.parametrize("anomaly", ("digest", "directory", "symlink", "owner", "hardlink"))
def test_existing_published_archive_anomaly_is_preserved_and_fails_before_nginx(tmp_path: Path, anomaly: str):
    base, target, calls, inert, commit, digest, env = _release_fixture(tmp_path, curl_mode="success")
    published = inert.parent / f"platform-routes-{commit}.tgz"
    if anomaly == "directory":
        published.mkdir()
    elif anomaly == "symlink":
        link_target = tmp_path / "published-link-target"
        link_target.write_bytes(inert.read_bytes())
        published.symlink_to(link_target)
    elif anomaly == "hardlink":
        hardlink_source = tmp_path / "published-hardlink-source"
        hardlink_source.write_bytes(inert.read_bytes())
        os.link(hardlink_source, published)
    elif anomaly == "digest":
        published.write_bytes(b"unexpected retained archive")
    else:
        shutil.copyfile(inert, published)
        real_stat = shutil.which("stat")
        assert real_stat
        _write_command(
            Path(env["PATH"].split(":", 1)[0]) / "stat",
            f'''if [[ "$1" == -c && "$2" == %U && "$3" == {str(published)!r} ]]; then
  printf 'unexpected-owner\\n'
  exit 0
fi
exec {real_stat!r} "$@"
''',
        )
    before_kind = (published.is_symlink(), published.is_dir())
    before_bytes = None if any(before_kind) else published.read_bytes()
    result = subprocess.run(
        ["bash", str(ROOT / "ops/platform-deploy/modules/platform"), str(inert), commit, digest, "DEPLOY_PLATFORM_ROUTES"],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert not inert.exists()
    assert (published.is_symlink(), published.is_dir()) == before_kind
    if before_bytes is not None:
        assert published.read_bytes() == before_bytes
    assert target.read_bytes() == base
    recorded = calls.read_text(encoding="utf-8")
    assert "nginx " not in recorded
    assert "systemctl " not in recorded
    assert "curl " not in recorded
    assert "active_sha256=" not in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="publish race test executes on Linux")
@pytest.mark.parametrize(("heads", "scp_count"), ((["b" * 40], 0), (["a" * 40, "b" * 40], 1)))
def test_publish_gate_rejects_late_head_drift_before_remote_activation(tmp_path: Path, heads: list[str], scp_count: int):
    archive = tmp_path / "platform-routes.tgz"
    archive.write_bytes(b"route archive")
    expected = "a" * 40
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "publish-calls"
    head_file = tmp_path / "heads"
    head_file.write_text("\n".join(heads) + "\n", encoding="utf-8")
    _write_command(
        fake_bin / "git",
        '''head="$(head -n 1 "$PLATFORM_TEST_HEADS")"
tail -n +2 "$PLATFORM_TEST_HEADS" > "$PLATFORM_TEST_HEADS.next"
mv "$PLATFORM_TEST_HEADS.next" "$PLATFORM_TEST_HEADS"
printf 'git %s -> %s\\n' "$*" "$head" >> "$PLATFORM_TEST_CALLS"
printf '%s\\trefs/heads/codex/production-sem\\n' "$head"
''',
    )
    for command in ("scp", "ssh"):
        _write_command(fake_bin / command, f'printf \'{command} %s\\n\' "$*" >> "$PLATFORM_TEST_CALLS"\n')
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "DEPLOY_HOST": "example.invalid",
            "DEPLOY_PORT": "22",
            "DEPLOY_USER": "platform-deploy",
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "PLATFORM_TEST_HEADS": str(head_file),
            "PLATFORM_TEST_CALLS": str(calls),
        }
    )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    result = subprocess.run(
        ["bash", str(ROOT / "ops/platform-deploy/publish-platform-routes.sh"), str(archive), expected, digest],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    recorded = calls.read_text(encoding="utf-8")
    assert recorded.count("scp ") == scp_count
    assert "ssh " not in recorded

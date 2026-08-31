"""Safety checks for the restricted SEM frontend deployment boundary."""

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_sem_frontend_deploy_uses_unprivileged_account_and_readable_modes():
    script = _read("frontend/scripts/deploy-sem.sh")

    assert "sem-deploy@101.200.193.83" in script
    assert "root@101.200.193.83" not in script
    assert "chown" not in script
    assert "--chmod=D0755,F0644" in script
    assert "StrictHostKeyChecking=yes" in script


def test_sem_ci_uses_pinned_host_key_and_dedicated_secret():
    workflow = _read(".github/workflows/ci.yml")

    assert "SEM_DEPLOY_SSH_KEY" in workflow
    assert "DEPLOY_KNOWN_HOSTS" in workflow
    assert "ssh-keyscan" not in workflow
    assert "DEPLOY_TARGET: sem-deploy@101.200.193.83" in workflow
    assert "environment: production" in workflow


def test_sem_frontend_release_rejects_stale_production_heads():
    workflow = _read(".github/workflows/ci.yml")
    script = _read("frontend/scripts/deploy-sem.sh")

    assert "group: production-sem-frontend-deployment" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "Require current SEM frontend production head" in workflow
    assert "RELEASE_BRANCH: codex/production-sem" in workflow
    assert 'git ls-remote origin "refs/heads/$RELEASE_BRANCH"' in workflow
    assert "Refusing stale SEM frontend release" in workflow

    assert "SEM_RELEASE_BRANCH:-codex/production-sem" in script
    assert "verify_release_head()" in script
    assert 'ls-remote origin "refs/heads/$release_branch"' in script
    deployment = script[script.index('if [[ "${VERIFY_ONLY:-0}" == "1" ]]') :]
    assert deployment.count("verify_release_head") == 2


def test_sem_frontend_keeps_element_plus_out_of_the_initial_bundle():
    package = json.loads(_read("frontend/package.json"))
    main = _read("frontend/src/main.js")
    vite_config = _read("frontend/vite.config.js")
    build_guard = _read("frontend/scripts/verify-sem-build.mjs")

    assert "unplugin-vue-components" in package["devDependencies"]
    assert "ElementPlusResolver" in vite_config
    assert "Components({" in vite_config
    assert "app.use(ElementPlus" not in main
    assert "use(ElementPlus" not in main
    assert "initialJavaScriptBudget = 500 * 1024" in build_guard


def test_sem_compatibility_routes_enter_the_real_dashboard():
    router = _read("frontend/src/router/index.js")
    diagnosis = _read("frontend/src/views/diagnosis/DiagnosisCenterView.vue")

    assert "path: '/sem',\n    redirect: '/monitor/dashboard'" in router
    assert (
        "path: '/deal-sniper/sem/dashboard',\n"
        "    redirect: '/monitor/dashboard'"
    ) in router
    assert 'href="/deal-sniper/sem/dashboard"' in diagnosis


def test_sem_release_requires_the_favicon_referenced_by_index():
    index = _read("frontend/index.html")
    build_guard = _read("frontend/scripts/verify-sem-build.mjs")
    deploy_script = _read("frontend/scripts/deploy-sem.sh")
    favicon = ROOT / "frontend/public/favicon-v2.png"

    assert 'href="/favicon-v2.png"' in index
    assert favicon.is_file()
    assert favicon.stat().st_size > 0
    assert "resolve(buildDir, 'favicon-v2.png')" in build_guard
    assert "test -s '${release_dir}/favicon-v2.png'" in deploy_script

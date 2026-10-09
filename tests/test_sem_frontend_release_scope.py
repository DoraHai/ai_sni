from scripts.sem_frontend_release_scope import requires_release


def test_customer_artifact_or_backend_change_does_not_publish_sem_frontend():
    assert not requires_release(['customer-workbench/js/connected-workbench.mjs',
        'ops/customer-workbench/package-release.mjs', '.github/workflows/ci.yml',
        'app/api/seo.py', 'scripts/sem_frontend_release_scope.py'])
    assert not requires_release([])


def test_sem_frontend_build_input_change_still_publishes():
    for path in ['frontend/src/App.vue', 'frontend/package-lock.json',
                 'frontend/scripts/deploy-sem.sh', 'integrations/workbench/client.mjs']:
        assert requires_release([path, 'customer-workbench/index.html'])

"""Status-only actual HTTPS pilot driver; no production credentials or device secrets."""
import argparse
import json
from pathlib import Path
import ssl
import os
from uuid import uuid4
import httpx

SCOPE = {'module': 'seo', 'tenant_id': 15, 'scope_id': 6}
SOURCE_REVISION = 'seo-m2-v1-351641b2519e96eda71a7a1236ca43db5c9e08f18cf82a31e56be3c52942d942'
CONTENT_DIGEST = '528da4b3dd69288446e0001f35cf86454abbc8be3ef608256c9a7a0123460958'


class Client:
    def __init__(self, root, module='seo', actor='admin', username=None):
        self.root = root
        config = json.loads((root / 'operator-login.json').read_text(encoding='utf-8'))
        origin = config['origins'][module]
        if config['production'] is not False or origin != {'seo': 'https://127.0.0.1:55861', 'geo': 'https://127.0.0.1:55862'}[module]:
            raise RuntimeError('OWNED_ACCEPTANCE_ORIGIN_REQUIRED')
        self.http = httpx.Client(base_url=origin, verify=ssl.create_default_context(cafile=str(root / 'loopback.pem')),
                                 trust_env=False, follow_redirects=False, timeout=20)
        self.journal = []
        login = self.http.post('/api/v1/auth/login', json={'username': username or config[actor + '_username'], 'password': config['password']})
        if login.status_code != 200:
            raise RuntimeError('NAMED_LOGIN_FAILED')
        self.http.headers['Authorization'] = 'Bearer ' + login.json()['token']

    def call(self, method, path, expected=200, **kwargs):
        response = self.http.request(method, path, **kwargs)
        value = response.json()
        detail = value.get('detail') if isinstance(value, dict) else None
        code = detail.get('code') if isinstance(detail, dict) else None
        self.journal.append({'method': method, 'path': path, 'status': response.status_code, 'code': code})
        if response.status_code not in (expected if isinstance(expected, tuple) else (expected,)):
            raise RuntimeError('ACTUAL_HTTP_CHECK_FAILED_' + str(response.status_code))
        return value

    def close(self):
        self.http.close()


def owned(value):
    root = Path(value).resolve(strict=True)
    if root.parent != Path(os.environ['TEMP']).resolve() or root.name != 'distribution-cloud-pilot-20261012':
        raise RuntimeError('OWNED_CLOUD_PILOT_REQUIRED')
    return root


def status(root):
    admin = Client(root)
    try:
        pair = json.loads((root / 'one-time-pairing-private.json').read_text(encoding='utf-8'))
        value = admin.call('GET', '/api/distribution/v1/device-pairings/' + pair['pairing_id'])
        devices = admin.call('GET', '/api/distribution/v1/devices')['items']
        device = next(row for row in devices if row['id'] == pair['device_id'])
        result = {'pairing': value['pairing'], 'device': device, 'http': admin.journal,
                  'production': False, 'publicationAttempted': False}
        (root / 'cloud-pairing-status.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    finally:
        admin.close()


def bind_unverified(root):
    admin, advisor = Client(root), Client(root, actor='advisor')
    try:
        pair = json.loads((root / 'one-time-pairing-private.json').read_text(encoding='utf-8'))
        ticket = admin.call('GET', '/api/distribution/v1/device-pairings/' + pair['pairing_id'])['pairing']
        if ticket['state'] != 'claimed':
            raise RuntimeError('ACTUAL_CLAIM_REQUIRED')
        admin.call('PUT', '/api/v1/seo/workbench/advisor-assignments', json={
            'tenant_id': 15, 'site_id': 6, 'advisor_user_id': 100007, 'active': True})
        rows = admin.call('GET', '/api/distribution/v1/bindings')['items']
        bindings = [row for row in rows if row['device_id'] == pair['device_id'] and row['active']]
        if not bindings:
            binding = admin.call('POST', '/api/distribution/v1/bindings', json={**SCOPE,
                'device_id': pair['device_id'], 'account_id': 'acceptance-seo',
                'external_account_id': 'acceptance-wechat-unverified', 'platform': 'wechat-article',
                'confirm_account_ownership': True})['binding']
        else:
            if len(bindings) != 1 or bindings[0]['external_account_id'] != 'acceptance-wechat-unverified':
                raise RuntimeError('UNEXPECTED_BINDING_STOP')
            binding = bindings[0]
        view = advisor.call('GET', '/api/distribution/v1/scope', params=SCOPE)
        if view['project']['state'] != 'paused' or view['capabilities']['automated_publish'] is not False:
            raise RuntimeError('PAUSED_NO_PUBLISH_REQUIRED')
        result = {'scope': SCOPE, 'binding': binding, 'projectState': 'paused',
                  'realAccountVerified': False, 'externalIdIsUnverifiedPlaceholder': True,
                  'automaticSubmit': False, 'publishingGrantIssued': False, 'tasksQueued': False,
                  'production': False, 'http': admin.journal + advisor.journal}
        (root / 'cloud-unverified-binding-evidence.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    finally:
        admin.close()
        advisor.close()


def guards(root):
    admin = Client(root)
    customer = Client(root, username='acceptance-customer-15')
    foreign = Client(root, username='acceptance-foreign-customer')
    try:
        customer.call('POST', '/api/distribution/v1/device-pairings', expected=403,
                      json={'label': 'forbidden-check', 'expires_in_seconds': 60, 'request_id': str(uuid4())})
        customer.call('POST', '/api/distribution/v1/control', expected=403,
                      json={**SCOPE, 'action': 'resume', 'expected_revision': 0, 'request_id': str(uuid4())})
        foreign.call('GET', '/api/distribution/v1/scope', expected=403, params=SCOPE)
        foreign.call('GET', '/api/distribution/v1/source', expected=403,
                     params={**SCOPE, 'variant_id': 1, 'platform': 'wechat-article'})
        admin.call('POST', '/api/distribution/v1/devices', expected=409, json={'label': 'legacy-create-forbidden'})
        with httpx.Client(base_url='https://127.0.0.1:55861',
                verify=ssl.create_default_context(cafile=str(root / 'loopback.pem')),
                trust_env=False, follow_redirects=False, timeout=20) as pc:
            for headers in ({'Authorization': 'Bearer not-a-device'}, {'Origin': 'https://127.0.0.1:55861'}, {'Sec-Fetch-Mode': 'cors'}):
                response = pc.post('/api/distribution/v1/device-pairings/claim', headers=headers,
                    json={'pairing_code': 'A' * 32, 'request_id': str(uuid4())})
                code = response.json().get('detail', {}).get('code')
                if response.status_code != 400 or code != 'PAIRING_DEVICE_ONLY':
                    raise RuntimeError('BROWSER_CLAIM_GUARD_FAILED_' + str(response.status_code))
                admin.journal.append({'method': 'POST', 'path': '/api/distribution/v1/device-pairings/claim',
                                      'status': response.status_code, 'code': code, 'context': next(iter(headers))})
        result = {'checks': admin.journal + customer.journal + foreign.journal,
                  'actualCloudHTTP': True, 'crossTenantBlocked': True, 'customerControlBlocked': True,
                  'legacyLongCredentialCreationBlocked': True, 'browserClaimBlocked': True,
                  'codeOrDeviceSecretIncluded': False, 'production': False, 'publicationAttempted': False}
        (root / 'cloud-authorization-guards.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    finally:
        for client in (admin, customer, foreign):
            client.close()


def catalog(root):
    result = {'production': False, 'modules': {}}
    for module in ('seo', 'geo'):
        admin = Client(root, module)
        try:
            me = admin.call('GET', '/api/v1/auth/me')['user']
            directory = admin.call('GET', '/api/v1/auth/modules')
            rows = directory['modules']
            available = [row['module_code'] for row in rows if row['available']]
            if me['id'] != 100008 or available != [module]:
                raise RuntimeError('NATIVE_MODULE_SCOPE_CHECK_FAILED')
            result['modules'][module] = {'actorId': me['id'], 'available': available, 'http': admin.journal}
        finally:
            admin.close()
    (root / 'cloud-native-module-catalog.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def preflight(root):
    path = root / 'cloud-single-preflight-intent.json'
    if path.exists():
        raise RuntimeError('SINGLE_PREFLIGHT_ALREADY_RECORDED_DO_NOT_RETRY')
    advisor = Client(root, actor='advisor')
    try:
        binding = json.loads((root / 'cloud-unverified-binding-evidence.json').read_text(encoding='utf-8'))['binding']
        source = advisor.call('GET', '/api/distribution/v1/source',
                              params={**SCOPE, 'variant_id': 2, 'platform': 'wechat-article'})
        if source['source_revision'] != SOURCE_REVISION or source['content_digest'] != CONTENT_DIGEST or source['content']['assets']:
            raise RuntimeError('EXACT_DERIVED_REVIEWED_SOURCE_REQUIRED')
        if advisor.call('GET', '/api/distribution/v1/tasks', params=SCOPE)['items']:
            raise RuntimeError('EMPTY_OWNED_TASK_QUEUE_REQUIRED')
        project = advisor.call('GET', '/api/distribution/v1/scope', params=SCOPE)['project']
        if project['state'] != 'paused' or project['revision'] != 0:
            raise RuntimeError('UNTOUCHED_PAUSED_SCOPE_REQUIRED')
        intent = {'phase': 'prepared', 'scope': SCOPE, 'request_id': str(uuid4()),
                  'variant_id': 2, 'binding_id': binding['id'], 'source_revision': SOURCE_REVISION,
                  'content_digest': CONTENT_DIGEST, 'action': 'preflight',
                  'production': False, 'publicationAttempted': False}
        with path.open('x', encoding='utf-8') as output:
            json.dump(intent, output, indent=2)
        advisor.call('POST', '/api/distribution/v1/control', json={**SCOPE,
                     'action': 'start', 'expected_revision': 0, 'request_id': str(uuid4())})
        intent['phase'] = 'project-started'
        path.write_text(json.dumps(intent, indent=2), encoding='utf-8')
        task = advisor.call('POST', '/api/distribution/v1/tasks', json={**SCOPE,
            'variant_id': 2, 'binding_id': binding['id'], 'source_revision': SOURCE_REVISION,
            'expected_digest': CONTENT_DIGEST, 'action': 'preflight', 'confirm_reviewed_content': True,
            'confirm_manual_publication': False, 'expires_in_seconds': 600, 'request_id': intent['request_id']})['task']
        intent.update(phase='queued', task=task, http=advisor.journal)
        path.write_text(json.dumps(intent, indent=2), encoding='utf-8')
        return intent
    except Exception:
        if path.exists():
            intent['phase'] = 'needs-investigation-do-not-retry'
            intent['http'] = advisor.journal
            path.write_text(json.dumps(intent, indent=2), encoding='utf-8')
        raise
    finally:
        advisor.close()


def preflight_status(root, pause=False):
    advisor = Client(root, actor='advisor')
    try:
        intent = json.loads((root / 'cloud-single-preflight-intent.json').read_text(encoding='utf-8'))
        tasks = advisor.call('GET', '/api/distribution/v1/tasks', params=SCOPE)['items']
        task = next(row for row in tasks if row['id'] == intent['task']['id'])
        if len(tasks) != 1 or task['action'] != 'preflight' or task['source_revision'] != SOURCE_REVISION:
            raise RuntimeError('EXACT_SINGLE_PREFLIGHT_REQUIRED')
        project = advisor.call('GET', '/api/distribution/v1/scope', params=SCOPE)['project']
        if pause:
            if task['status'] != 'awaiting-human' or task['receipt']['code'] not in ('HUMAN_REQUIRED', 'LOGIN_REQUIRED', 'CAPTCHA'):
                raise RuntimeError('ACTUAL_HUMAN_WAIT_RECEIPT_REQUIRED')
            if project['state'] != 'running':
                raise RuntimeError('RUNNING_OWNED_TEST_SCOPE_REQUIRED')
            project = advisor.call('POST', '/api/distribution/v1/control', json={**SCOPE,
                'action': 'pause', 'expected_revision': project['revision'], 'request_id': str(uuid4())})['project']
        result = {'task': task, 'project': project, 'actualCloudHTTP': True,
                  'formalPublicationAttempted': False, 'automaticPublicationGranted': False,
                  'production': False, 'http': advisor.journal}
        (root / ('cloud-single-preflight-paused.json' if pause else 'cloud-single-preflight-status.json')).write_text(
            json.dumps(result, indent=2), encoding='utf-8')
        return result
    finally:
        advisor.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('status', 'bind-unverified', 'guards', 'catalog', 'preflight', 'preflight-status', 'preflight-pause'))
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    root = owned(args.root)
    action = {'status': status, 'bind-unverified': bind_unverified, 'guards': guards, 'catalog': catalog,
              'preflight': preflight, 'preflight-status': preflight_status,
              'preflight-pause': lambda root: preflight_status(root, pause=True)}[args.action]
    print(json.dumps(action(root), ensure_ascii=True))

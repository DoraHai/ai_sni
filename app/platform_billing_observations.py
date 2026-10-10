"""Owner-provided dated observations, never promoted to current API results."""
from datetime import datetime, date
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from app.platform_balances import amount


def load_observations(settings):
    empty = {'schema': 1, 'state': 'unavailable', 'reported_balances': [], 'packages': [], 'services': [],
             'note': '人工核验记录未读取；不影响实时账务接口查询。'}
    try:
        configured = getattr(settings, 'platform_billing_observations_path', '')
        path = Path(configured) if configured else Path(__file__).resolve().parent.parent / 'config/platform_billing_observations.json'
        with path.open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            return empty
        data = json.loads(raw)
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
        if data.get('schema') != 1 or data.get('source') != 'owner_console_verification':
            return empty
        observed = date.fromisoformat(data['verified_on'])
        if observed > today:
            return empty
        reported, packages, services = [], [], []
        if len(data.get('reported_balances', [])) > 10 or len(data.get('packages', [])) > 50:
            return empty
        for row in data.get('reported_balances', []):
            if row['provider'] not in {'aliyun', 'volcengine', 'qianfan', 'tencent'} or row['currency'] != 'CNY':
                return empty
            reported.append({'provider': row['provider'], 'name': str(row['name'])[:100],
                'currency': 'CNY', 'amount': amount(row['amount']), 'basis': str(row['basis'])[:200]})
        ids = set()
        for row in data.get('packages', []):
            if row['id'] in ids or any(type(row[k]) is not int or row[k] < 0 for k in ('total', 'used', 'remaining')):
                return empty
            ids.add(row['id'])
            if not row['total'] or row['used'] + row['remaining'] != row['total'] or type(row['enabled']) is not bool:
                return empty
            expiry = date.fromisoformat(row['expires_on'])
            warning = 'exhausted' if row['remaining'] == 0 else 'low' if row['remaining'] * 10 <= row['total'] else 'normal'
            packages.append({'id': str(row['id'])[:100], 'name': str(row['name'])[:100],
                **{k: row[k] for k in ('total', 'used', 'remaining', 'enabled')},
                'expires_on': expiry.isoformat(), 'quota_warning': warning,
                'expiry_warning': 'expired' if expiry < today else 'expiring' if (expiry - today).days <= 30 else 'normal'})
        for row in data.get('services', []):
            if row['id'] != 'tencent_wsa' or row['state'] != 'not_opened':
                return empty
            services.append({'id': row['id'], 'name': str(row['name'])[:100], 'state': row['state'], 'note': str(row['note'])[:300]})
        account = data.get('package_account')
        if not isinstance(account, dict) or account['provider'] != 'chinaz' or account['currency'] != 'CNY':
            return empty
        public_account = {'provider': 'chinaz', 'name': str(account['name'])[:100], 'account_id': str(account['account_id'])[:100],
                          'currency': 'CNY', 'balance': amount(account['balance']), 'note': str(account['note'])[:400]}
        return {'schema': 1, 'state': 'available', 'source': 'owner_console_verification',
            'verified_on': observed.isoformat(), 'freshness': 'verified_today' if observed == today else 'needs_recheck',
            'reported_balances': reported, 'package_account': public_account, 'packages': packages, 'services': services,
            'note': '金额和余量为所标日期的用户核验记录。实时查询不会改写人工记录；核验日期过后应重新核对套餐余量。'}
    except Exception:
        # No paths, key material or raw file content may appear in the response.
        return empty

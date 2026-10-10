"""Human proof attestation for one exact ledger event. Never calls a provider."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import re
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import text

from app.api_controls import ControlConflict, decimal_value, enabled, lock, schema_ready
from app.api_usage_review_basis import REVIEW_COLUMNS, review_columns

AUDIT_COLUMNS = {'request_id','event_id','actor_id','request_hash','review_version',
                 'evidence','before_value','after_value','created_at'}
STATES = {'requested','unknown','succeeded','error'}
SOURCES = {'provider_request_record','provider_billing_record','provider_support_record'}
FIELDS = 'id,state,endpoint,provider_request_id,started_at,estimated_amount,currency,review_version,verified_amount,verified_currency,reviewed_at'


def enabled_review():
    return enabled() and os.getenv('API_USAGE_REVIEW_ENABLED', '').lower() == 'true'


async def status(session):
    cols = await review_columns(session)
    audit = set((await session.execute(text("""SELECT column_name FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name='api_usage_review_audit'"""))).scalars())
    ready = cols == REVIEW_COLUMNS and AUDIT_COLUMNS <= audit
    admission_ready = await schema_ready(session) if ready else False
    return {'schema':1, 'state': ('enabled' if enabled_review() and admission_ready else 'ready') if ready else 'schema_pending',
            'capabilities':['usage_review_v1'] if ready else []}


def safe_text(value, maximum, minimum=1):
    if not isinstance(value,str) or not minimum <= len(value.strip()) <= maximum or any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError('核实证据字段无效')
    return value.strip()


def validate(data):
    keys = {'request_id','event_id','expected_version','expected_state','terminal_state',
            'provider_request_id','verified_amount','currency','evidence'}
    if not isinstance(data,dict) or set(data)!=keys:
        raise ValueError('核实字段不完整')
    result = dict(data)
    for key in ('request_id','event_id'):
        if not isinstance(result[key],str):
            raise ValueError('核实记录标识无效')
        result[key] = str(UUID(result[key]))
    version = result['expected_version']
    if type(version) is not int or not 0 <= version < 2**31-1:
        raise ValueError('核实版本无效')
    if result['expected_state'] not in STATES or result['terminal_state'] not in {'succeeded','error'}:
        raise ValueError('必须有供应商确认的终态')
    result['provider_request_id'] = safe_text(result['provider_request_id'],100)
    evidence = result['evidence']
    expected = {'source','provider_host','reference','sha256','summary','observed_at',
                'terminal_confirmed','zero_charge_confirmed'}
    if not isinstance(evidence,dict) or set(evidence)!=expected or evidence['source'] not in SOURCES:
        raise ValueError('证据来源无效')
    evidence = dict(evidence)
    if evidence['terminal_confirmed'] is not True or type(evidence['zero_charge_confirmed']) is not bool:
        raise ValueError('须人工核对供应商终态证据')
    host = evidence['provider_host']
    if not isinstance(host,str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?',host):
        raise ValueError('证据服务商地址无效')
    reference = safe_text(evidence['reference'],300)
    if '://' in reference:
        parts = urlsplit(reference)
        if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError('证据索引不能包含登录信息或查询参数')
    evidence['reference'] = reference
    evidence['summary'] = safe_text(evidence['summary'],1000,10)
    if not isinstance(evidence['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',evidence['sha256']):
        raise ValueError('证据文件指纹无效')
    moment = datetime.fromisoformat(safe_text(evidence['observed_at'],40).replace('Z','+00:00'))
    if moment.tzinfo is None or moment.utcoffset().total_seconds()!=0:
        raise ValueError('证据时间须为 UTC')
    evidence['observed_at'] = moment.isoformat()
    amount = result['verified_amount']
    if amount is None:
        if result['currency'] is not None or evidence['zero_charge_confirmed']:
            raise ValueError('金额未知时不得标注币种或零扣款')
    else:
        if not isinstance(amount,str) or result['currency']!='CNY' or evidence['source']=='provider_request_record':
            raise ValueError('费用须有人民币账单或供应商客服证据')
        amount = decimal_value(amount)
        if Decimal(amount)==0 and evidence['zero_charge_confirmed'] is not True:
            raise ValueError('零费用须明确核对供应商零扣款证据')
        if Decimal(amount)!=0 and evidence['zero_charge_confirmed']:
            raise ValueError('非零费用不能确认零扣款')
    result['verified_amount'], result['evidence'] = amount, evidence
    return result


def public_row(raw,reviewed_provider_request_id=None):
    from app.api.platform_console import safe_endpoint
    row = dict(raw)
    row['id'] = str(row['id'])
    row['endpoint'] = safe_endpoint(row['endpoint'])
    row['reviewed_provider_request_id'] = reviewed_provider_request_id
    for key in ('verified_amount','estimated_amount'):
        row[key] = None if row[key] is None else format(row[key],'f')
    for key in ('started_at','reviewed_at'):
        row[key] = row[key].isoformat() if row[key] else None
    row['can_review'] = enabled_review() and (row['state'] in {'requested','unknown'} or
        row['verified_amount'] is None and row['estimated_amount'] is None or
        row['review_version']>0 and row['verified_amount'] is None)
    return row


async def frozen_provider_id(session,raw):
    if raw['review_version']==0:
        return None
    latest = (await session.execute(text('''SELECT review_version,evidence FROM api_usage_review_audit
        WHERE event_id=CAST(:event AS uuid) ORDER BY review_version DESC LIMIT 1'''),
        {'event':str(raw['id'])})).mappings().one_or_none()
    if not latest or latest['review_version']!=raw['review_version'] or not isinstance(latest['evidence'],dict):
        raise ControlConflict('历史核实证据版本不完整，须先审查记录，不能继续补费用')
    value=latest['evidence'].get('provider_request_id')
    try:
        return safe_text(value,100)
    except ValueError:
        raise ControlConflict('历史核实证据缺少供应商请求标识，不能重新绑定调用') from None


async def read_review(session,event_id):
    readiness = await status(session)
    if readiness['state']=='schema_pending':
        return {'schema':1,'state':'schema_pending','row':None}
    row = (await session.execute(text(f'SELECT {FIELDS} FROM api_usage_events WHERE id=CAST(:id AS uuid)'),
                                 {'id':str(UUID(str(event_id)))})).mappings().one_or_none()
    frozen = await frozen_provider_id(session,row) if row else None
    return {'schema':1,'state':'available','row':public_row(row,frozen) if row else None}


async def mutate_review(session,actor_id,data):
    data = validate(data)
    await lock(session)
    if (await status(session))['state']!='enabled':
        raise RuntimeError('Usage review not enabled')
    request_hash = hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    existing = (await session.execute(text('SELECT actor_id,request_hash,after_value FROM api_usage_review_audit WHERE request_id=CAST(:id AS uuid)'),
                                          {'id':data['request_id']})).mappings().one_or_none()
    if existing:
        if existing['actor_id']!=actor_id or existing['request_hash']!=request_hash:
            raise ControlConflict('核实请求标识已用于另一操作，请重新读取记录')
        return {'schema':1,'state':'available','replayed':True,'row':existing['after_value']}
    raw = (await session.execute(text(f'SELECT {FIELDS} FROM api_usage_events WHERE id=CAST(:id AS uuid) FOR UPDATE'),
                                 {'id':data['event_id']})).mappings().one_or_none()
    if not raw:
        raise ControlConflict('调用记录不存在，请重新读取台账')
    if raw['review_version']!=data['expected_version'] or raw['state']!=data['expected_state']:
        raise ControlConflict('调用状态或核实版本已变化，请重新读取并核对证据')
    frozen = await frozen_provider_id(session,raw)
    if frozen is not None and frozen!=data['provider_request_id']:
        raise ValueError('供应商请求标识与已冻结的人工核实证据不一致')
    if raw['state'] in {'succeeded','error'} and raw['state']!=data['terminal_state']:
        raise ValueError('已有确定终态不能被改成另一终态')
    if raw['review_version']>0 and raw['verified_amount'] is not None:
        raise ControlConflict('本记录费用已有核实结论，不能覆盖')
    if raw['state'] in {'succeeded','error'} and raw['review_version']==0 and raw['estimated_amount'] is not None:
        raise ValueError('本接口仅用于结果未知或费用未知的调用')
    host = (raw['endpoint'] or '').split('/')[0]
    if data['evidence']['provider_host']!=host:
        raise ValueError('证据服务商与调用不一致')
    if raw['provider_request_id'] and raw['provider_request_id']!=data['provider_request_id']:
        raise ValueError('供应商请求标识与调用不一致')
    observed = datetime.fromisoformat(data['evidence']['observed_at'])
    if observed < raw['started_at'] or (observed-datetime.now(timezone.utc)).total_seconds()>60:
        raise ValueError('证据时间与调用不一致')
    before = public_row(raw,frozen)
    updated = (await session.execute(text(f'''UPDATE api_usage_events SET state=:state,
        review_version=review_version+1,verified_amount=CAST(:amount AS numeric),verified_currency=:currency,
        reviewed_at=CURRENT_TIMESTAMP WHERE id=CAST(:id AS uuid) RETURNING {FIELDS}'''),
        {'state':data['terminal_state'],'amount':data['verified_amount'],'currency':data['currency'],'id':data['event_id']})).mappings().one()
    after = public_row(updated,data['provider_request_id'])
    evidence = {**data['evidence'],'provider_request_id':data['provider_request_id']}
    await session.execute(text('''INSERT INTO api_usage_review_audit
        (request_id,event_id,actor_id,request_hash,review_version,evidence,before_value,after_value)
        VALUES(CAST(:request AS uuid),CAST(:event AS uuid),:actor,:hash,:version,
            CAST(:evidence AS jsonb),CAST(:before AS jsonb),CAST(:after AS jsonb))'''),
        {'request':data['request_id'],'event':data['event_id'],'actor':actor_id,'hash':request_hash,
         'version':updated['review_version'],'evidence':json.dumps(evidence,ensure_ascii=False),
         'before':json.dumps(before,ensure_ascii=False),'after':json.dumps(after,ensure_ascii=False)})
    await session.commit()
    return {'schema':1,'state':'available','replayed':False,'row':after}

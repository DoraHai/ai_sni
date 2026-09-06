"""Conservative page identity and durable links to repeated diagnoses."""
from urllib.parse import urlsplit, urlunsplit


def page_identity(url):
    try:
        p = urlsplit(url or '')
        if p.scheme.lower() not in {'http', 'https'} or not p.hostname or p.username or p.password:
            return None
        host = p.hostname.lower()
        if ':' in host:
            host = '[' + host + ']'
        port = p.port
        if port and (p.scheme.lower(), port) not in {('http', 80), ('https', 443)}:
            host += ':' + str(port)
        # Queries, path case, trailing slash and scheme may identify different pages.
        return urlunsplit((p.scheme.lower(), host, p.path or '/', p.query, ''))
    except ValueError:
        return None


def link_diagnosis(ticket, audit_id):
    baseline = dict(ticket.baseline_snapshot or {})
    ids = list(baseline.get('diagnosis_ids') or [])
    for value in (ticket.audit_id, audit_id):
        if value is not None and value not in ids:
            ids.append(value)
    baseline['diagnosis_ids'] = ids
    ticket.baseline_snapshot = baseline


def audit_ticket_filter(model, audit_id):
    from sqlalchemy import or_
    return or_(model.audit_id == audit_id,
               model.baseline_snapshot.contains({'diagnosis_ids': [audit_id]}))

import asyncio
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.datastructures import FormData, UploadFile
from app.config import get_settings
from app.database import Base
from app.models.seo import SeoContentAsset, SeoDistributionConnection, SeoSiteAdvisorAssignment
from app.security import advisor_write_commit
from app.security.advisor_tenant_auth import enforce_advisor_request
from app.security.seo_advisor_execution import recheck_before_provider
from app.security.seo_advisor_reads import install_query_scope
from app.security.seo_advisor_uploads import request_body
from test_advisor_scoped_writes_objects import object_db, selected  # noqa: F401
from test_advisor_tenant_auth import local_db  # noqa: F401
from test_seo_advisor_work import req


@pytest.mark.parametrize('content_id,tenant,enabled', [(1,1,True), (101,1,True), (201,1,True), (301,1,True), (1,2,True), (1,1,False)])
def test_publish_admission_keeps_client_assignment_and_switch(object_db, monkeypatch, content_id, tenant, enabled):
    db, session = object_db
    Base.metadata.create_all(db.bind, tables=[SeoDistributionConnection.__table__])
    db.add(SeoDistributionConnection(id=10, tenant_id=1, platform_code='wordpress', name='fixture', mode='api', config={'advisor_site_id': 1}))
    db.commit()
    monkeypatch.setattr(get_settings(), 'advisor_scoped_content_writes_enabled', enabled)
    body = {'tenant_id': tenant, 'content_id': content_id, 'connection_id': 10, 'action': 'publish', 'confirm': True}
    request = req('POST', '/api/v1/seo/content-distribution/publish', body, query=f'tenant_id={tenant}')
    if (content_id,tenant,enabled) == (1,1,True):
        asyncio.run(enforce_advisor_request(request, selected(), session))
        assert session._seo_advisor_context.user_id == 1
    else:
        with pytest.raises(HTTPException): asyncio.run(enforce_advisor_request(request, selected(), session))


def test_revocation_before_provider_stops_and_records_external_attempt(monkeypatch, caplog):
    request, ctx = req(keyword_id=20), selected()
    session = SimpleNamespace(_seo_advisor_context=ctx, _seo_advisor_request=request)
    check = AsyncMock(side_effect=HTTPException(401, 'revoked'))
    monkeypatch.setattr(advisor_write_commit, 'recheck_advisor_before_commit', check)
    with caplog.at_level('INFO', logger='seo.advisor.operations'):
        with pytest.raises(HTTPException): asyncio.run(recheck_before_provider(session, 42))
    event = json.loads(caplog.records[-1].message)
    assert event['result'] == 'external_call_blocked' and event['publication_id'] == 42
    assert event['user_id'] == 1 and event['tenant_id'] == 1


def test_bulk_import_cannot_reach_a_second_assigned_site(object_db):
    db, session = object_db
    db.add(SeoSiteAdvisorAssignment(id=2, tenant_id=1, site_id=4, advisor_user_id=1, active=True)); db.commit()
    ctx, request = selected(), req(keyword_id=20)
    request.state.seo_advisor_site_id = 1
    ctx.advisor_write_scope = (request, {}, None)
    install_query_scope(session, ctx)
    assert list(db.scalars(select(SeoContentAsset.id))) == [1]


def test_multipart_cursor_is_restored_and_extra_files_are_rejected():
    upload = UploadFile(BytesIO(b'fixture'), filename='links.xlsx')
    upload.file.seek(2)
    request = SimpleNamespace(form=AsyncMock(return_value=FormData([('file', upload)])))
    rule = SimpleNamespace(template='/api/v1/seo/content-assets/import-published-links')
    assert asyncio.run(request_body(request, rule)) == {}
    assert upload.file.tell() == 2
    request.form.return_value = FormData([('file', upload), ('file', upload)])
    with pytest.raises(HTTPException): asyncio.run(request_body(request, rule))

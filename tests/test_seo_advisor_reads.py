import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import aliased
from app.models.seo import SeoContentAsset, SeoSiteAdvisorAssignment
from app.models.module_workspace import SeoSite
from app.security.seo_advisor_reads import install_query_scope
from app.security.advisor_tenant_auth import check_seo_objects
from test_advisor_scoped_writes_objects import object_db, selected  # noqa: F401
from test_advisor_tenant_auth import local_db  # noqa: F401
from test_seo_advisor_work import req


def test_assignment_filters_lists_totals_aliases_and_core_rows(object_db):
    db, session = object_db
    install_query_scope(session, selected())
    assert list(db.scalars(select(SeoContentAsset.id))) == [1]
    assert db.scalar(select(func.count()).select_from(SeoContentAsset)) == 1
    model = aliased(SeoContentAsset)
    assert list(db.scalars(select(model.id))) == [1]
    assert [row.id for row in db.execute(select(SeoContentAsset.__table__))] == [1]
    assert list(db.scalars(select(SeoSite.id))) == [1]


@pytest.mark.parametrize('kind,object_id', [('content_id', 301), ('site_id', 4), ('content_id', 101), ('content_id', 201)])
def test_explicit_read_rejects_other_projects_and_customers(object_db, kind, object_id):
    request = req('GET', '/api/v1/seo/content-assets', query=f'tenant_id=1&{kind}={object_id}')
    with pytest.raises(HTTPException):
        asyncio.run(check_seo_objects(request, selected(), object_db[1]))


def test_revoked_assignment_and_inactive_site_disappear_from_reads(object_db):
    db, session = object_db
    install_query_scope(session, selected())
    assignment = db.get(SeoSiteAdvisorAssignment, 1)
    assignment.active = False
    db.commit()
    assert list(db.scalars(select(SeoContentAsset.id))) == []

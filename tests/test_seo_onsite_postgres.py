"""Concurrency uses only a dedicated loopback PostgreSQL database and owned schemas."""
import asyncio
from uuid import uuid4
import os
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.schema import CreateTable
from test_seo_workflow_postgres import database, ADVISOR
from app.api import seo_onsite as api
from app.models.seo import SeoSitePage
from app.models.seo_cockpit import SeoTask

pytestmark=pytest.mark.skipif(not os.getenv("SEO_WORKFLOW_TEST_DATABASE_URL"), reason="requires dedicated PostgreSQL")

def test_create_and_proposal_races_are_serialized_without_lost_history():
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                await db.execute(CreateTable(SeoSitePage.__table__, include_foreign_key_constraints=[]))
                await db.commit()
            req=api.Create(tenant_id=4,site_id=2,request_id=uuid4(),work_type="startup",owner_name="维护人员")
            async def create():
                async with sessions() as db:
                    return await api.create(req,db,ADVISOR)
            rows=await asyncio.gather(*(create() for _ in range(5)))
            assert len({r["id"] for r in rows})==1
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(SeoTask))==1
            row=rows[0]
            async def save():
                async with sessions() as db:
                    try:
                        return await api.act(row["id"],api.Update(tenant_id=4,site_id=2,action="save_proposal",
                            expected_revision=1,items=row["workflow"]["items"]),db,ADVISOR)
                    except HTTPException as exc:
                        assert exc.status_code==409
                        return None
            results=await asyncio.gather(*(save() for _ in range(5)))
            assert sum(r is not None for r in results)==1
            async with sessions() as db:
                task=await db.get(SeoTask,row["id"])
                assert task.params["onsite"]["revision"]==2 and len(task.params["onsite"]["history"])==2
            async with sessions() as db:
                with pytest.raises(HTTPException) as err:
                    await api.create(req.model_copy(update={"owner_name":"其他人员"}),db,ADVISOR)
                assert err.value.status_code==409
    asyncio.run(run())


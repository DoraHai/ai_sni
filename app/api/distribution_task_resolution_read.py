"""Device credential only, bounded private history read, not a publication API."""
from fastapi import APIRouter, Depends, Request
from app.database import get_session
from app.api.distribution import PrivateRoute, device_credential
from app.distribution_task_resolution_contract import TaskResolutionRead, TaskResolutionReadView
from app import distribution_task_resolution_read

router = APIRouter(prefix='/api/distribution/v1/device',route_class=PrivateRoute,
                   tags=['设备历史结果核查读取'])


@router.post('/task-resolution',response_model=TaskResolutionReadView)
async def device_task_resolution(req:TaskResolutionRead,request:Request,db=Depends(get_session)):
    return await distribution_task_resolution_read.read(db,device_credential(request),req)

"""影子API工厂；本地及生产适配均保留可信鉴权依赖。"""
from __future__ import annotations

from datetime import datetime, timezone
import inspect
from sqlalchemy.exc import SQLAlchemyError
from app.sem_phase0.store import StorageUnavailable

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from fastapi.responses import Response
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from app.sem_phase1a.errors import ShadowError
from starlette.concurrency import run_in_threadpool

from app.sem_phase0.store import AdvisorPrincipal, RevisionConflict, ScopeDenied
from app.sem_phase1a.contracts import ApplyRequest, ApprovalRequest, CreateRequest, RulingRequest, BatchCreateRequest, StructureRequest
from app.sem_phase1a.excel import MAX_XLSX_BYTES
from app.sem_phase1a.service import ShadowService


class _SafeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(422, {"code": "CONTRACT_INVALID", "message": "请求不满足演练契约"}) from None
        return handler


def create_router(service: ShadowService, resolve_principal):
    router = APIRouter(prefix="/api/v1/sem/phase1a/shadow", tags=["SEM合成影子演练"], route_class=_SafeRoute)

    async def invoke(function, *args, write=True):
        try:
            if inspect.iscoroutinefunction(function):
                return await function(*args)
            return await run_in_threadpool(function, *args)
        except StorageUnavailable as exc:
            raise HTTPException(503, {"code": exc.code, "message": "来源或附件存储暂不可用"}) from None
        except SQLAlchemyError:
            raise HTTPException(503, {"code": "SOURCE_STORAGE_UNAVAILABLE", "message": "来源存储暂不可用"}) from None
        except ScopeDenied:
            message = "无该租户账户的顾问提交权限" if write else "无该租户账户的读取权限"
            raise HTTPException(403, {"code": "SCOPE_DENIED", "message": message}) from None
        except RevisionConflict:
            raise HTTPException(409, {"code": "VERSION_CONFLICT", "message": "来源/规划/预览版本已失效"}) from None
        except KeyError:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "合成演练记录不存在"}) from None
        except ShadowError as exc:
            raise HTTPException(422, {"code": exc.code, "message": "演练检查未通过，请按错误码修订"}) from None
        except PermissionError:
            raise HTTPException(403, {"code": "OPERATION_FORBIDDEN", "message": "该演练操作未获准"}) from None
        except ValueError:
            raise HTTPException(422, {"code": "CONTRACT_INVALID", "message": "演练契约或检查不满足"}) from None

    @router.get('/accounts/{account_id}/plans')
    async def listing(account_id: int, tenant_id: int = Query(gt=0),
                      offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100),
                      principal: AdvisorPrincipal = Depends(resolve_principal)):
        if account_id <= 0:
            raise HTTPException(422, {'code': 'CONTRACT_INVALID'})
        return await invoke(service.list_plans, principal, tenant_id, account_id, offset, limit, write=False)

    @router.post("/plans", status_code=201)
    async def create(body: CreateRequest, principal: AdvisorPrincipal = Depends(resolve_principal)):
        return await invoke(service.create, principal, body)

    @router.post("/plans/batch", status_code=201)
    async def create_batch(body: BatchCreateRequest, principal: AdvisorPrincipal = Depends(resolve_principal)):
        return await invoke(service.create, principal, body)

    @router.post("/plans/{plan_id}/structure")
    async def structure(plan_id: str, body: StructureRequest, principal: AdvisorPrincipal = Depends(resolve_principal)):
        return await invoke(service.edit_structure, principal, plan_id, body)

    @router.get("/plans/{plan_id}")
    async def read(plan_id: str, principal: AdvisorPrincipal = Depends(resolve_principal)):
        return await invoke(service.read, principal, plan_id, write=False)

    @router.post("/plans/{plan_id}/rulings")
    async def ruling(plan_id: str, body: RulingRequest, principal: AdvisorPrincipal = Depends(resolve_principal)):
        return await invoke(service.rule, principal, plan_id, body)

    @router.get("/plans/{plan_id}/excel/{audience}")
    async def export(plan_id: str, audience: str, principal: AdvisorPrincipal = Depends(resolve_principal)):
        data = await invoke(service.export, principal, plan_id, audience)
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="internal-rehearsal-not-for-baidu.xlsx"'})

    @router.post("/plans/{plan_id}/previews/{audience}")
    async def preview(plan_id: str, audience: str, file: UploadFile = File(...),
                      principal: AdvisorPrincipal = Depends(resolve_principal)):
        try:
            if not (file.filename or "").lower().endswith(".xlsx"):
                raise HTTPException(422, {"code": "EXCEL_INVALID_OR_TAMPERED", "message": "仅接受内部XLSX"})
            # 在读附件前完成账户权限检查。
            view = await invoke(service.read, principal, plan_id, write=False)
            from app.sem_phase0.store import check_scope
            await invoke(check_scope, principal, view["submission"]["tenant_id"], view["submission"]["account_id"])
            data = await file.read(MAX_XLSX_BYTES+1)
            return await invoke(service.preview, principal, plan_id, data, audience)
        finally:
            await file.close()

    @router.post("/plans/{plan_id}/apply-preview")
    async def apply(plan_id: str, body: ApplyRequest, principal: AdvisorPrincipal = Depends(resolve_principal)):
        return await invoke(service.apply, principal, plan_id, body)

    @router.post("/plans/{plan_id}/approvals")
    async def approve(plan_id: str, body: ApprovalRequest, principal: AdvisorPrincipal = Depends(resolve_principal)):
        return await invoke(service.approve, principal, plan_id, body)

    @router.get("/plans/{plan_id}/expiry-suggestions")
    async def expiry(plan_id: str, now: datetime | None = None,
               principal: AdvisorPrincipal = Depends(resolve_principal)):
        return await invoke(service.expiry, principal, plan_id, now or datetime.now(timezone.utc), write=False)

    return router

"""不挂app.main的合成API工厂，权限仅由可信服务端依赖注入。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.sem_phase0.store import AdvisorPrincipal, RevisionConflict, ScopeDenied
from app.sem_phase1a.contracts import ApplyRequest, ApprovalRequest, CreateRequest, RulingRequest
from app.sem_phase1a.excel import MAX_XLSX_BYTES
from app.sem_phase1a.service import ShadowService


def create_router(service: ShadowService, resolve_principal):
    router = APIRouter(prefix="/api/v1/sem/phase1a/shadow", tags=["SEM合成影子演练"])

    def invoke(function, *args):
        try:
            return function(*args)
        except ScopeDenied:
            raise HTTPException(403, "无该合成账户的顾问权限") from None
        except RevisionConflict:
            raise HTTPException(409, "来源/规划/预览版本已失效，请重新读取或创建") from None
        except KeyError:
            raise HTTPException(404, "合成演练记录不存在") from None
        except (ValueError, PermissionError):
            raise HTTPException(422, "演练契约/检查不满足；请核对版本、来源、格式及硬阻断") from None

    @router.post("/plans", status_code=201)
    def create(body: CreateRequest, principal: AdvisorPrincipal = Depends(resolve_principal)):
        return invoke(service.create, principal, body)

    @router.get("/plans/{plan_id}")
    def read(plan_id: str, principal: AdvisorPrincipal = Depends(resolve_principal)):
        return invoke(service.read, principal, plan_id)

    @router.post("/plans/{plan_id}/rulings")
    def ruling(plan_id: str, body: RulingRequest, principal: AdvisorPrincipal = Depends(resolve_principal)):
        return invoke(service.rule, principal, plan_id, body)

    @router.get("/plans/{plan_id}/excel/{audience}")
    def export(plan_id: str, audience: str, principal: AdvisorPrincipal = Depends(resolve_principal)):
        data = invoke(service.export, principal, plan_id, audience)
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="internal-rehearsal-not-for-baidu.xlsx"'})

    @router.post("/plans/{plan_id}/previews/{audience}")
    async def preview(plan_id: str, audience: str, file: UploadFile = File(...),
                      principal: AdvisorPrincipal = Depends(resolve_principal)):
        try:
            if not (file.filename or "").lower().endswith(".xlsx"):
                raise HTTPException(422, "仅接受本模块内部XLSX")
            # 在读附件前完成账户权限检查。
            invoke(service.read, principal, plan_id)
            data = await file.read(MAX_XLSX_BYTES+1)
            return await run_in_threadpool(invoke, service.preview, principal, plan_id, data, audience)
        finally:
            await file.close()

    @router.post("/plans/{plan_id}/apply-preview")
    def apply(plan_id: str, body: ApplyRequest, principal: AdvisorPrincipal = Depends(resolve_principal)):
        return invoke(service.apply, principal, plan_id, body)

    @router.post("/plans/{plan_id}/approvals")
    def approve(plan_id: str, body: ApprovalRequest, principal: AdvisorPrincipal = Depends(resolve_principal)):
        return invoke(service.approve, principal, plan_id, body)

    @router.get("/plans/{plan_id}/expiry-suggestions")
    def expiry(plan_id: str, now: datetime | None = None,
               principal: AdvisorPrincipal = Depends(resolve_principal)):
        return invoke(service.expiry, principal, plan_id, now or datetime.now(timezone.utc))

    return router

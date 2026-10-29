"""可挂接SEM入口：必须显式注入鉴权和独立存储；生产挂载仍需真实鉴权和账户绑定。"""
from __future__ import annotations
import inspect
from sqlalchemy.exc import SQLAlchemyError
from app.sem_phase0.store import StorageUnavailable
from app.sem_phase1a.router import _SafeRoute

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.sem_phase0.contracts import LandingSubmission
from app.sem_phase0.screenshots import MAX_IMAGE_BYTES, MAX_IMAGES, MAX_TOTAL_BYTES, Screenshot
from app.sem_phase0.store import AdvisorPrincipal, RevisionConflict, ScopeDenied, SubmissionRepository, check_scope


def create_router(store: SubmissionRepository, resolve_principal) -> APIRouter:
    """resolve_principal必须是可信FastAPI依赖，无匿名/客户/通用API-key回退。"""
    router = APIRouter(prefix="/api/v1/sem/phase0", tags=["SEM阶段0内部契约"], route_class=_SafeRoute)

    async def invoke(method, *args):
        if inspect.iscoroutinefunction(method):
            return await method(*args)
        return await run_in_threadpool(method, *args)

    @router.post("/submissions", status_code=201)
    async def submit(metadata: str = Form(...),
                     screenshots: list[UploadFile] = File(default=[]),
                     principal: AdvisorPrincipal = Depends(resolve_principal)):
        try:
            if len(metadata) > 250000:
                raise ValueError("输入元数据过长")
            payload = LandingSubmission.model_validate_json(metadata)
            check_scope(principal, payload.tenant_id, payload.account_id)
            if len(screenshots) > MAX_IMAGES:
                raise ValueError("截图数量超限")
            images = []
            total = 0
            for upload in screenshots:
                data = await upload.read(MAX_IMAGE_BYTES + 1)
                total += len(data)
                if len(data) > MAX_IMAGE_BYTES or total > MAX_TOTAL_BYTES:
                    raise ValueError("截图大小超限")
                images.append(Screenshot(payload.landing_page_id, upload.filename or "",
                                         upload.content_type or "", data))
            return await invoke(store.submit, principal, payload, images)
        except StorageUnavailable as exc:
            raise HTTPException(503, {"code": exc.code, "message": "来源或附件存储暂不可用"}) from None
        except SQLAlchemyError:
            raise HTTPException(503, {"code": "SOURCE_STORAGE_UNAVAILABLE", "message": "来源存储暂不可用"}) from None
        except ScopeDenied:
            raise HTTPException(403, "无该租户账户的顾问提交权限") from None
        except RevisionConflict:
            raise HTTPException(409, {"code": "VERSION_CONFLICT", "message": "提交版本冲突"}) from None
        except ValidationError:
            # Even extra-field names can be attacker-controlled; echo no loc/input.
            raise HTTPException(422, {"code": "CONTRACT_INVALID",
                                      "message": "输入契约不满足，请补齐字段并核对情况/日期"}) from None
        except ValueError:
            raise HTTPException(422, {"code": "CONTRACT_INVALID", "message": "提交不满足契约"}) from None
        finally:
            for upload in screenshots:
                await upload.close()

    @router.get("/submissions/{tenant}/{account}/{page}/{revision}")
    async def read(tenant: int, account: int, page: str, revision: int,
             principal: AdvisorPrincipal = Depends(resolve_principal)):
        try:
            result = await invoke(store.read,principal, tenant, account, page, revision)
        except StorageUnavailable as exc:
            raise HTTPException(503, {"code": exc.code, "message": "来源或附件存储暂不可用"}) from None
        except SQLAlchemyError:
            raise HTTPException(503, {"code": "SOURCE_STORAGE_UNAVAILABLE", "message": "来源存储暂不可用"}) from None
        except ScopeDenied:
            raise HTTPException(403, "无该租户账户的顾问提交权限") from None
        except ValueError:
            raise HTTPException(422, {"code": "SOURCE_INVALID", "message": "来源校验失败"}) from None
        if result is None:
            raise HTTPException(404, "无该页面提交版本")
        return result

    return router

"""Account grant router; production mounting retains real administrator auth."""
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.sem_phase1a.grant_management import GrantError
from app.sem_phase1a.router import _SafeRoute


class GrantRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    tenant_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    advisor_grant_id: int | None = Field(default=None, gt=0)


def create_grant_router(service, resolve_admin=None):
    if resolve_admin is None:
        from app.security.auth import require_admin
        resolve_admin = require_admin
    router = APIRouter(prefix='/api/v1/sem/phase1a/account-grants', route_class=_SafeRoute,
                       tags=['SEM影子账户授权管理'])

    async def invoke(fn, *args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except GrantError as exc:
            raise HTTPException(exc.status, {'code': exc.code, 'message': '账户授权检查未通过'}) from None
        except IntegrityError:
            raise HTTPException(409, {'code': 'GRANT_CONFLICT', 'message': '账户授权状态冲突'}) from None
        except (SQLAlchemyError, ValueError, TypeError):
            raise HTTPException(503, {'code': 'GRANT_STORAGE_UNAVAILABLE', 'message': '账户授权暂不可用'}) from None

    @router.get('/accounts/{account_id}')
    async def listing(account_id: int = Path(gt=0), tenant_id: int = Query(gt=0), ctx=Depends(resolve_admin)):
        return await invoke(service.list_grants, ctx, tenant_id, account_id)

    @router.post('/accounts/{account_id}')
    async def grant(body: GrantRequest, account_id: int = Path(gt=0), ctx=Depends(resolve_admin)):
        return await invoke(service.change, ctx, body.tenant_id, account_id, body.user_id, body.advisor_grant_id)

    @router.post('/accounts/{account_id}/revoke')
    async def revoke(body: GrantRequest, account_id: int = Path(gt=0), ctx=Depends(resolve_admin)):
        return await invoke(service.change, ctx, body.tenant_id, account_id, body.user_id, revoke=True)

    return router

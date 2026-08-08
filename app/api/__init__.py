from app.api.adjustments_verify import router as adjustments_verify_router
from app.api.alerts import router as alerts_router
from app.api.assistant import router as assistant_router
from app.api.auth import router as auth_router
from app.api.customer_profile import router as customer_profile_router
from app.api.dashboard import router as dashboard_router
from app.api.expansion import router as expansion_router
from app.api.keywords import router as keywords_router
from app.api.leads import router as leads_router
from app.api.manage import router as manage_router
from app.api.negatives import router as negatives_router
from app.api.ocpc import router as ocpc_router
from app.api.oauth_baidu import (
    callback_router as baidu_oauth_callback_router,
    router as baidu_oauth_router,
)
from app.api.onboarding_builder import router as onboarding_builder_router
from app.api.operations import router as operations_router
from app.api.reports import router as reports_router
from app.api.roles import router as roles_router
from app.api.search_terms import router as search_terms_router
from app.api.structure import router as structure_router
from app.api.suggestions import router as suggestions_router
from app.api.insights import router as insights_router
from app.api.users import router as users_router
from app.api.writeback import router as writeback_router
from app.api.geo import router as geo_router

__all__ = [
    "adjustments_verify_router",
    "alerts_router",
    "assistant_router",
    "auth_router",
    "customer_profile_router",
    "users_router",
    "dashboard_router",
    "expansion_router",
    "keywords_router",
    "leads_router",
    "manage_router",
    "negatives_router",
    "ocpc_router",
    "baidu_oauth_router",
    "baidu_oauth_callback_router",
    "onboarding_builder_router",
    "operations_router",
    "reports_router",
    "roles_router",
    "structure_router",
    "suggestions_router",
    "insights_router",
    "writeback_router",
    "search_terms_router",
    "geo_router",
]

"""Engine switches and patrol schedules are platform administrator settings."""
from fastapi import HTTPException


def require_geo_configuration_admin(ctx):
    if ctx.tenant_id is not None or not ctx.can_edit('settings.accounts'):
        raise HTTPException(403, '只有平台管理员可以修改检测引擎或巡检频率，请联系管理员处理')

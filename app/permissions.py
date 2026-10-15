"""菜单级权限注册表（自定义角色 RBAC 的权限点定义）。

权限点 = 左侧导航的叶子菜单。每个角色对每个菜单可授「可见(view) / 可编辑(edit)」两级，
未授予 = 无权访问。edit 蕴含 view。前后端共用这份 key 清单（前端 constants/menus.js 同步）。

后端鉴权（app/security/auth.py）按请求路径反查菜单键 + HTTP 方法定 view/edit。
"""

# 菜单注册表：key 唯一，group 用于侧边栏分组，path 是前端路由（settings.accounts 仅 edit 有意义）
MENUS: list[dict] = [
    {"key": "sem.assets", "label": "推广账号", "group": "SEM 资产", "path": "/sem/accounts"},
    {"key": "seo.assets", "label": "网站管理", "group": "SEO 增长", "path": "/seo/sites"},
    {"key": "geo.assets", "label": "项目管理", "group": "GEO 增长", "path": "/geo/projects"},
    {"key": "assistant", "label": "AI 助手", "group": "智能助手", "path": "/assistant"},
    {"key": "geo.diagnosis", "label": "GEO 诊断", "group": "GEO 增长", "path": "/geo/diagnosis"},
    {"key": "geo.content", "label": "GEO 概览", "group": "GEO 增长", "path": "/geo/overview"},
    {"key": "seo.dashboard", "label": "排名看板", "group": "SEO 增长", "path": "/seo/dashboard"},
    {"key": "seo.alerts", "label": "异常提醒", "group": "SEO 增长", "path": "/seo/alerts"},
    {"key": "seo.keywords", "label": "关键词资产", "group": "SEO 增长", "path": "/seo/keywords"},
    {"key": "seo.content", "label": "内容创作", "group": "SEO 增长", "path": "/seo/content"},
    {"key": "seo.site", "label": "站内优化", "group": "SEO 增长", "path": "/seo/site"},
    {"key": "seo.links", "label": "内外链管理", "group": "SEO 增长", "path": "/seo/links"},
    {"key": "seo.competitors", "label": "竞品监控", "group": "SEO 增长", "path": "/seo/competitors"},
    {"key": "onboarding", "label": "授权与同步", "group": "首次接入", "path": "/onboarding"},
    {"key": "monitor.dashboard", "label": "数据看板", "group": "每日盯盘", "path": "/monitor/dashboard"},
    {"key": "monitor.alerts", "label": "异常提醒", "group": "每日盯盘", "path": "/monitor/alerts"},
    {"key": "monitor.profile", "label": "客户画像", "group": "每日盯盘", "path": "/monitor/profile"},
    {"key": "optimize.expand", "label": "拓词", "group": "优化执行", "path": "/optimize/expand"},
    {"key": "optimize.keywords", "label": "关键词工作台", "group": "优化执行", "path": "/optimize/keywords"},
    {"key": "optimize.searchterms", "label": "搜索词报告", "group": "优化执行", "path": "/optimize/search-terms"},
    {"key": "optimize.negatives", "label": "否词管理", "group": "优化执行", "path": "/optimize/negatives"},
    {"key": "verify.adjustments", "label": "调价台账", "group": "效果验证", "path": "/verify/adjustments"},
    {"key": "verify.pending", "label": "待验证调价", "group": "效果验证", "path": "/verify/pending"},
    {"key": "verify.leads", "label": "线索管理", "group": "效果验证", "path": "/verify/leads"},
    {"key": "manage.account", "label": "账户与预算", "group": "投放管理", "path": "/manage/account"},
    {"key": "manage.campaigns", "label": "计划管理", "group": "投放管理", "path": "/manage/campaigns"},
    {"key": "manage.adgroups", "label": "单元管理", "group": "投放管理", "path": "/manage/adgroups"},
    {"key": "manage.ocpc", "label": "oCPC 投放", "group": "投放管理", "path": "/manage/ocpc"},
    {"key": "delivery.report", "label": "分析报告", "group": "客户交付", "path": "/delivery/report"},
    {"key": "settings.accounts", "label": "账号与权限", "group": "系统设置", "path": "/settings/accounts"},
    {"key": "settings.customers", "label": "客户与模块", "group": "系统设置", "path": "/settings/customers"},
]

MENU_KEYS: set[str] = {m["key"] for m in MENUS}
LEVELS = ("view", "edit")

# 内置系统角色的种子权限（迁移 0016 seed + 冒烟复用）。is_system=True 不可删。
ALL_EDIT = {m["key"]: "edit" for m in MENUS}
# 运营：除「账号与权限」外全部可编辑
OPERATOR_PERMS = {
    k: "edit" for k in MENU_KEYS if k not in {"settings.accounts", "settings.customers"}
}
# 品牌方客户：只读看板 + 画像 + 报告
CLIENT_PERMS = {
    "sem.assets": "edit",
    "seo.assets": "edit",
    "geo.assets": "edit",
    "monitor.dashboard": "view",
    "monitor.profile": "view",
    "delivery.report": "view",
    "geo.diagnosis": "view",
    "geo.content": "view",
    "seo.keywords": "view",
    "seo.site": "view",
    "seo.dashboard": "view",
    "seo.alerts": "view",
    "seo.content": "view",
    "seo.links": "view",
    "seo.competitors": "view",
}

SYSTEM_ROLES = [
    {"name": "管理员", "description": "全部菜单可编辑，含账号与角色管理", "permissions": ALL_EDIT},
    {"name": "运营", "description": "日常优化工作流全部可编辑，不含账号管理", "permissions": OPERATOR_PERMS},
    {"name": "品牌方客户", "description": "只读：数据看板 + 分析报告（通常绑定单客户）", "permissions": CLIENT_PERMS},
]


def normalize_permissions(perms: dict) -> dict[str, str]:
    """清洗角色权限：丢掉非法菜单键/非法等级，保证只含 MENU_KEYS × LEVELS。"""
    out: dict[str, str] = {}
    if not isinstance(perms, dict):
        return out
    for k, v in perms.items():
        if k in MENU_KEYS and v in LEVELS:
            out[k] = v
    return out

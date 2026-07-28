"""自定义角色 RBAC 冒烟：登录/JWT/菜单级 view-edit 鉴权/租户隔离/角色 CRUD/系统角色保护/
权限即时生效/API Key 超管/不能停自己。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_auth.py
"""
import asyncio

from sqlalchemy import delete, select

from app.database import async_session_factory, engine
from app.models import Role, Tenant, User

failed = False


def check(label, cond, detail=""):
    global failed
    mark = "✅" if cond else "❌"
    if not cond:
        failed = True
    print(f"{mark} {label} {detail}")


async def seed():
    async with async_session_factory() as s:
        ids = []
        for name in ("认证冒烟租户A", "认证冒烟租户B"):
            t = await s.scalar(select(Tenant).where(Tenant.name == name))
            if t is None:
                t = Tenant(name=name, monthly_budget=1000)
                s.add(t)
                await s.flush()
            ids.append(t.id)
        await s.execute(delete(User).where(User.username.like("smoke_%")))
        # 清掉上次遗留的测试角色（先删用户再删角色，避免外键占用）
        await s.execute(delete(Role).where(Role.name.in_(["投放专员冒烟", "临时角色冒烟"])))
        await s.commit()
        result = (ids[0], ids[1])
    await engine.dispose()  # 同一 loop 内 dispose，避免跨 loop 报错
    return result


TID_A, TID_B = asyncio.run(seed())

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

KEY = {"X-API-Key": get_settings().admin_api_key}


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def login(client, username, password="pw_smoke_123"):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


with TestClient(app) as client:
    # ===== 无凭证 / API Key 超管 =====
    check("无凭证 401", client.get("/api/v1/keywords", params={"tenant_id": TID_A}).status_code == 401)
    me = client.get("/api/v1/auth/me", headers=KEY).json()["user"]
    check("API Key=超管 + 全权限",
          me["role_label"] == "超级管理员" and me["permissions"].get("settings.accounts") == "edit")

    # ===== 角色清单（内置 3）=====
    roles = client.get("/api/v1/roles", headers=KEY).json()
    rid = {r["name"]: r["id"] for r in roles["roles"]}
    check("内置 3 角色存在", {"管理员", "运营", "品牌方客户"} <= set(rid))
    check("角色清单带菜单注册表", any(m["key"] == "optimize.expand" for m in roles["menus"]))

    # ===== 建自定义角色：盯盘可见 + 异常可见 + 拓词可编辑 =====
    r = client.post("/api/v1/roles", headers=KEY, json={
        "name": "投放专员冒烟",
        "permissions": {"monitor.dashboard": "view", "monitor.alerts": "view", "optimize.expand": "edit"},
    })
    check("建自定义角色", r.status_code == 200, r.text[:100])
    custom_id = r.json()["id"]

    def mkuser(username, role_id, tenant_id=None):
        return client.post("/api/v1/users", headers=KEY, json={
            "username": username, "password": "pw_smoke_123", "role_id": role_id, "tenant_id": tenant_id,
        })

    check("建专员账号", mkuser("smoke_op", custom_id).status_code == 200)
    check("建客户账号(绑A)", mkuser("smoke_client", rid["品牌方客户"], TID_A).status_code == 200)
    check("建管理员账号", mkuser("smoke_admin", rid["管理员"]).status_code == 200)
    check("非法 role_id 404", mkuser("smoke_bad", 999999).status_code == 404)

    # ===== 专员：菜单 view/edit 鉴权 =====
    op = login(client, "smoke_op")
    check("专员登录 ok", op.status_code == 200)
    oph = bearer(op.json()["token"])
    check("专员 permissions 下发", op.json()["user"]["permissions"].get("optimize.expand") == "edit")
    check("专员看板可见(view) 200",
          client.get("/api/v1/dashboard/today", params={"tenant_id": TID_A}, headers=oph).status_code == 200)
    check("专员异常列表可见 200",
          client.get("/api/v1/alerts", params={"tenant_id": TID_A}, headers=oph).status_code == 200)
    check("专员异常写=403(仅可见)",
          client.patch("/api/v1/alerts/999999/resolve", headers=oph).status_code == 403)
    check("专员月报=403(无权限)",
          client.get("/api/v1/reports/monthly", params={"tenant_id": TID_A, "year": 2026, "month": 5},
                     headers=oph).status_code == 403)
    check("专员拓词可见 200",
          client.get("/api/v1/expansion/candidates", params={"tenant_id": TID_A}, headers=oph).status_code == 200)
    check("专员账号管理=403", client.get("/api/v1/users", headers=oph).status_code == 403)

    # ===== 客户：租户隔离 =====
    cl = login(client, "smoke_client")
    clh = bearer(cl.json()["token"])
    check("客户绑定 A 下发 tenant_id", cl.json()["user"]["tenant_id"] == TID_A)
    check("客户看 A 看板 200",
          client.get("/api/v1/dashboard/today", params={"tenant_id": TID_A}, headers=clh).status_code == 200)
    check("客户看 B 看板=403(租户隔离)",
          client.get("/api/v1/dashboard/today", params={"tenant_id": TID_B}, headers=clh).status_code == 403)
    check("客户无异常权限=403",
          client.get("/api/v1/alerts", params={"tenant_id": TID_A}, headers=clh).status_code == 403)
    check("客户切换器只回绑定租户",
          [t["id"] for t in client.get("/api/v1/auth/tenants", headers=clh).json()["tenants"]] == [TID_A])

    # ===== 系统角色保护 =====
    check("内置角色不可删 400",
          client.delete(f"/api/v1/roles/{rid['管理员']}", headers=KEY).status_code == 400)
    check("管理员不可移除账号管理权 400",
          client.patch(f"/api/v1/roles/{rid['管理员']}", headers=KEY,
                       json={"permissions": {"monitor.dashboard": "edit"}}).status_code == 400)
    check("有账号的自定义角色不可删 400",
          client.delete(f"/api/v1/roles/{custom_id}", headers=KEY).status_code == 400)

    # ===== 权限即时生效：给专员角色加异常 edit，无需重登 =====
    client.patch(f"/api/v1/roles/{custom_id}", headers=KEY, json={
        "permissions": {"monitor.dashboard": "view", "monitor.alerts": "edit", "optimize.expand": "edit"},
    })
    check("加 edit 后专员异常写即时放行(404 非 403)",
          client.patch("/api/v1/alerts/999999/resolve", headers=oph).status_code == 404)

    # ===== 不能停用自己 =====
    adm = login(client, "smoke_admin")
    admh = bearer(adm.json()["token"])
    own_id = adm.json()["user"]["id"]
    check("管理员可进账号管理 200", client.get("/api/v1/users", headers=admh).status_code == 200)
    check("不能停用自己 400",
          client.patch(f"/api/v1/users/{own_id}", headers=admh, json={"is_active": False}).status_code == 400)

    # ===== 空角色可删 =====
    tmp_id = client.post("/api/v1/roles", headers=KEY, json={"name": "临时角色冒烟", "permissions": {}}).json()["id"]
    check("空角色可删 200", client.delete(f"/api/v1/roles/{tmp_id}", headers=KEY).status_code == 200)

print("\n冒烟失败" if failed else "\n冒烟全部通过")
raise SystemExit(1 if failed else 0)

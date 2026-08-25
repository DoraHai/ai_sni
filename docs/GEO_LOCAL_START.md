# GEO 工作台本地启动

当前签约交付面是 **Vue SPA（`:5173`）+ 主站 FastAPI（`:8000`）**。静态原型台 `:5176` 与独立 `geo_main` `:8011` 仍可跑，但不是日常入口。

## 1. 环境

| 依赖 | 说明 |
| --- | --- |
| Python 3.11+ | 本机可用 Miniconda，`python` 需能 `import uvicorn`、`asyncpg` / SQLAlchemy |
| Node 20+ | `frontend/` 用 Vite 8 |
| PostgreSQL | `.env` 里 `DATABASE_URL` 指向的库 |
| 仓库根 `.env` | 从 `.env.example` 复制；本地 `APP_ENV=dev`，`ADMIN_API_KEY` 与前端 `VITE_API_KEY` 一致 |

Windows 示例（工作树或主仓均可，把路径换成你的 clone）：

```powershell
cd C:\Users\白泽\Projects\ai_sni
# 若还没有 .env
Copy-Item .env.example .env
```

`frontend/.env` 或 `frontend/.env.local`：

```text
VITE_API_KEY=geo-demo-local-key
```

须与仓库根 `.env` 的 `ADMIN_API_KEY` 相同。Vite 只在开发态用这个 Key；生产构建不得内嵌。

## 2. 数据库

```powershell
cd C:\Users\白泽\Projects\ai_sni
# 激活你的 venv / conda 后
alembic upgrade head
```

可选种子（tenant 1 演示数据）：

```powershell
python scripts/seed_geo_demo.py
```

## 3. 启动后端（必须用 `app.main`，定时巡检挂在这里）

```powershell
# 仓库根，加载 .env
python -c "from dotenv import load_dotenv; load_dotenv(); import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=8000, reload=True)"
```

健康检查：

```text
http://127.0.0.1:8000/health/geo
http://127.0.0.1:8000/api/v1/geo/content-health
```

`8000` 被占用时先结束旧进程，或改端口并同步 `frontend` 的 `VITE_API_PROXY_TARGET`。

## 4. 启动前端

```powershell
cd frontend
npm install
npm run dev
```

默认 `http://127.0.0.1:5173`，`/api` 反代到 `:8000`。

## 5. 登录

1. 打开 `http://127.0.0.1:5173/login`
2. 用库里的账号密码登录（图形验证码是前端防呆，看页面字母即可）
3. 侧栏切到 GEO 工作台，默认 `/geo/overview`

未登录时，开发态可用 `VITE_API_KEY` 调 API（租户常回落到 1）。生产必须登录。

## 6. 页面地图（canonical 名称）

| 侧栏 / 页标题 | 路径 |
| --- | --- |
| GEO 概览 | `/geo/overview` |
| AI 可见度 | `/geo/visibility` |
| 采集与判断 | `/geo/visibility/snapshots` |
| 优化意图词 | `/geo/questions` |
| 竞品分析 | `/geo/competitors` |
| AI 引用次数 | `/geo/citations` |
| 知识库 | `/geo/knowledge` |
| 优化文章 | `/geo/tasks` |
| 内容编辑器 | `/geo/tasks/:taskId` |
| 信源策略 | `/geo/placements` |
| 分发平台 | `/geo/publishing` |
| 品牌资料 | `/geo/brand` |
| AI 能力配置 | `/geo/ai-settings` |
| 渠道成稿提示词 | `/geo/channel-polish-prompts` |
| 引擎（含巡检定时写入口） | `/geo/models` |

旧入口仍保留重定向，例如 `/geo/businesses` → `/geo/brand`，`/geo/deliverables` → `/geo/overview`，`/geo/engines` → `/geo/models`。只读分享仍是 `/geo/deliverables/share/:token`。

## 7. 机器验收

```powershell
cd frontend
npm run build

cd ..
python scripts/verify_productization_must.py
```

前端没有 lint 脚本。`npm run build` 能抓删文件后的残留 import。

## 8. 推荐手测

- `/geo/overview`、`/geo/visibility/snapshots`：查询期只在顶栏出现一次
- `/geo/models`：Kimi / Perplexity 等配了百炼地址时，顶栏不再有「保存」；弹窗保存只校验当前引擎
- 设置六页（品牌资料、知识库、渠道成稿提示词、信源策略、分发平台、引擎、AI 能力配置）无查询期

更完整的点击链见 `docs/GEO_CLICK_TEST_CHAIN.md`、`docs/GEO_DELIVERY_CHECKLIST.md`。

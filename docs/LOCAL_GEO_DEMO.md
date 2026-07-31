# GEO 本地联调入口（先不提交也可用）

> 端口刻意错开，避免再出现「打开 diagnostic-center 却 404」。

## 端口一览

| 服务 | 端口 | 启动 |
| --- | --- | --- |
| GEO 内容工作台（静态） | **5176** | `python -m http.server 5176`（目录见下） |
| Vue 诊断中心 | **5174** | `npm run dev:diagnostic-center` |
| GEO API（`geo_main`） | **8011** | `uvicorn app.geo_main:app --host 127.0.0.1 --port 8011` |
| （可选）主站 Vue | 5173 | `npm run dev` |
| （可选）主站 API | 8000 | `uvicorn app.main:app --host 127.0.0.1 --port 8000` |

说明：本机若 **8010** 被旧进程占用，统一用 **8011**。诊断中心开发代理已指向 8011。

## 入口 URL

**GEO 内容闭环**

```text
http://127.0.0.1:5176/geo/dashboard.html?tenant_id=1&api_key=geo-demo-local-key&api_origin=http://127.0.0.1:8011
```

编辑器示例：

```text
http://127.0.0.1:5176/geo/editor.html?tenant_id=1&api_key=geo-demo-local-key&api_origin=http://127.0.0.1:8011&task_id=5
```

**诊断中心（含「创建 GEO 内容任务」）**

```text
http://127.0.0.1:5174/diagnostic-center/
```

需先登录主站拿到 `sem_token`，或在开发环境用带 API Key 的后端鉴权（见下）。

**一键跳转页（静态根）**

```text
http://127.0.0.1:5176/geo-demo.html
```

## 推荐启动顺序

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_local_geo_demo.ps1
```

或手动：

```powershell
# 终端 1 — GEO API
cd C:\Users\白泽\Projects\ai_sni
.\.venv\Scripts\python.exe -m uvicorn app.geo_main:app --host 127.0.0.1 --port 8011

# 终端 2 — GEO 静态
cd C:\Users\白泽\Projects\ai_sni\frontend\public\deal-sniper-prototype
python -m http.server 5176 --bind 127.0.0.1

# 终端 3 — 诊断中心（需 Node >= 20）
cd C:\Users\白泽\Projects\ai_sni\frontend
npm install
npm run dev:diagnostic-center
```

## 鉴权

| 方式 | 用法 |
| --- | --- |
| API Key | 本地 Demo：`geo-demo-local-key`（对应 `.env` 的 `ADMIN_API_KEY`），请求头 `X-API-Key` |
| 登录态 | 主站登录后浏览器存 `sem_token`；`frontend/src/api/client.js` 优先 `Authorization: Bearer`，无 token 时才用 `VITE_API_KEY` |

验证（本机）：

- 无 Key 访问 `/api/v1/geo/prompts` → **401**
- 带 `X-API-Key: geo-demo-local-key` → **200**
- 诊断中心开发可用 `diagnostic-center/.env.development.local` 里的 `VITE_API_KEY` 绕过登录（仅 DEV）

API Key **只鉴权本机 GEO/主站后端**，不接外部第三方。

## 诊断 → 内容桥

1. 打开诊断中心 → 跑诊断 → 生成行动建议  
2. 点「创建 GEO 内容任务 →」  
3. 应新开：`http://127.0.0.1:5176/geo/editor.html?...`  
4. 不必再走完整回填；能进编辑器即桥接成功  

API 已验证示例：`POST /content-tasks/from-diagnosis` → `editor_path` 指向 5176 编辑器。

## 四项验收怎么测

公共入口（先起 8011 + 5176）：

```text
http://127.0.0.1:5176/geo/dashboard.html?tenant_id=1&api_key=geo-demo-local-key&api_origin=http://127.0.0.1:8011
```

### 1) CSV 导入（行级错误）

1. 打开侧栏 **事实库 / 信源**
2. 点 **下载样例 CSV**（或用 `assets/sample-facts.csv`）
3. 选择该文件 → **CSV 导入**
4. 预期：顶部绿/红提示框显示「导入成功 10 条，失败 2 条」，并列出第 N 行错误；列表刷新出新事实

### 2) 一键插补丁

1. 打开任一已有正文的任务编辑器（或生成母稿后）
2. 页面会自动「检查就绪」；右侧出现 **插入修复 · faq_min / conclusion_extractable / updated_at_visible** 等按钮（缺什么出什么）
3. 也可手动删掉正文里的 FAQ/结论/更新时间 → **检查就绪** → 点插入 → 再检查，对应项应变绿

### 3) 未就绪回填 → HTTP 400

1. 选一个**尚未生成双渠道版**或规则未全过的任务
2. 打开 **分发平台**，填任意 `https://example.com/x` → **回填**
3. 预期：红色错误条出现后端门禁文案（API 返回 **400**），不会写成已发布

对照：同一任务先在编辑器点 **生成双渠道版** 并把规则修到就绪后，再回填应成功。

### 4) Dashboard 待办数字 ↔ 列表

1. 在 **GEO 概览** 看「待修规则 / 待导出 / 待回填 URL / 来自诊断」数字
2. 分别点击这些数字卡片
3. 预期：跳到 **GEO 文章** 列表，筛选命中条数与概览数字一致（列表上方有「当前筛选命中 N 条」）

### 5) 可见度人工快照（Wave B）

1. 打开 **提问监控**，确认有带 `brand_missing` 的机会问题（或新建并带该标签）
2. 点行内 **可见度**，或侧栏 **AI 可见度**
3. 选择该问题 → 粘贴一段回答 → 勾选「提及我方品牌」→ **保存快照**
4. 预期：右侧列表出现记录；回到提问监控刷新后，该问题的 `brand_missing` 标签消失
5. 列表内可点「切换」改提及状态；`competitors.html` / `evaluation.html` 仍为开发中

### 6) 引擎管理 + 媒体信源（Wave B2）

1. 侧栏打开 **AI 引擎管理**，停用某一个引擎 → **保存**
2. 回到 **AI 可见度**，登记表单下拉应不再出现该引擎
3. 打开 **媒体 / 信源策略**，新建一条「计划中」布局并保存；列表内改状态为「已铺设」并填 URL
4. **GEO 概览** 应出现真实计数：回答快照 / 提及品牌 / 信源布局进行中 / 信源已铺设
5. 先执行 migration：`alembic upgrade head`（含 `0039_geo_wave_b2`）

## 常见 404

| 错误打开 | 原因 |
| --- | --- |
| `5175/diagnostic-center/` | 诊断中心在 **5174**；5175 若仍是旧静态服务则无此路径 |
| `5176/dashboard.html`（无 `/geo/`） | 正确路径带 `/geo/` |
| `5176/geo/...` 但 API Failed to fetch | 确认 8011 已起，或 URL 带 `api_origin=http://127.0.0.1:8011` |

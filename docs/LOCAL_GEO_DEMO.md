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

1. 选一个**尚未生成渠道稿**或规则未全过的任务
2. 打开 **分发平台**，填任意 `https://example.com/x` → **回填**
3. 预期：红色错误条出现后端门禁文案（API 返回 **400**），不会写成已发布

对照：同一任务先在编辑器勾选渠道并点 **生成所选渠道稿**，规则修到就绪后，再回填应成功。

### 3b) 渠道适配（中国主渠道）

1. 编辑器底部勾选：官网 / 公众号 / 知乎（可选百家号、头条号）
2. 点 **生成所选渠道稿** → 出现渠道 Tab；公众号稿应含「参考说明」
3. 改母稿并 **保存母稿** 后，渠道 Tab 应标「过期」
4. 分发平台列表显示中文渠道名与「同步/过期」；复制后可回填 URL
5. 先 `alembic upgrade head`（含 `0040_geo_channel_adapt`）

### 4) Dashboard 待办数字 ↔ 列表

1. 在 **GEO 概览** 看「待修规则 / 待导出 / 待回填 URL / 来自诊断」数字
2. 分别点击这些数字卡片
3. 预期：跳到 **GEO 文章** 列表，筛选命中条数与概览数字一致（列表上方有「当前筛选命中 N 条」）

### 5) 可见度人工快照（Wave B）

1. 打开 **提问监控**，确认有带 `brand_missing` 的机会问题（或新建并带该标签）
2. 点行内 **可见度**，或侧栏 **AI 可见度**
3. 选择该问题 → 粘贴一段回答 → 勾选「提及我方品牌」→ **保存快照**
4. 预期：右侧列表出现记录；回到提问监控刷新后，该问题的 `brand_missing` 标签消失
5. 列表内可点「切换」改提及状态；竞品/评价见 §8

### 6) 引擎管理 + 媒体信源（Wave B2）

1. 侧栏打开 **AI 引擎管理**，停用某一个引擎 → **保存**
2. 回到 **AI 可见度**，登记表单下拉应不再出现该引擎
3. 打开 **媒体 / 信源策略**，新建一条「计划中」布局并保存；列表内改状态为「已铺设」并填 URL
4. **GEO 概览** 应出现真实计数：回答快照 / 提及品牌 / 信源布局进行中 / 信源已铺设
5. 先执行 migration：`alembic upgrade head`（含 `0039_geo_wave_b2`）

### 7) 可见度复核闭环（Wave B3）

1. **GEO 概览** 应出现「未提及品牌 / 待复核可见度」卡片；分别点击进入 `prompts.html?tag=brand_missing` 与 `visibility.html?queue=recheck`
2. **提问监控**：可用标签筛选；列表「最近观测」列显示提及状态 / 引擎 / 时间；带 `need_recheck` 时显示待复核
3. **分发平台**：URL 回填成功后出现「去登记可见度」→ 跳到对应 `prompt_id` 的可见度页
4. **AI 能力配置**（侧栏设置）：默认「阿里云百炼」，粘贴百炼 API Key → 保存 → 测试连通
   - 也可在 `.env` 配 `DASHSCOPE_API_KEY` 作为兜底
5. **AI 可见度**：可选「用 AI 探测」预填正文；无 Key 时提示去配置页或改用粘贴；确认后仍点「保存快照」入库
6. 保存「未提及」快照会加回 `brand_missing`；保存「提及」会清除该标签
7. migration 需包含 `0042_geo_ai_settings`（AI 能力配置表）

### 8) 竞品 / 评价 / 简单分（Wave C）

1. 先执行 migration：`alembic upgrade head`（含 `0041_geo_wave_c` / `0042_geo_ai_settings`）
2. **AI 可见度**：保存快照时填写竞品名、我方位置、情感倾向
3. 打开 **竞品分析**：应按竞品名看到出现次数 / 关联提问 / 引擎
4. 打开 **评价分析**：应看到情感与位置分布，以及最近快照列表
5. **GEO 概览**：出现「提及率」「引擎覆盖」「含竞品标注」真实计数（提及率 = 提及快照 / 全部快照）

### 8b) 引用域名聚合（Citation Insights）

1. **AI 可见度**：保存快照时在「引用 URL」粘贴若干链接（如知乎 / 头条 / 官网）
2. 侧栏打开 **引用域名**：应按去 www 后的主机名聚合出现次数 / 提问 / 引擎；知乎等应带蓝图阵地标签
3. 在 **发布渠道配置** 为官网填 `base_url` 后刷新：摘要出现「自有域引用率」；命中官网域名的行标「自有」
4. **GEO 概览**：出现「含引用 URL」「引用域名数」真实计数；无引用时为 0，不造假百分比

### 8c) 正文抽取引用 URL

1. **AI 可见度**：粘贴一段含 `https://…` 的回答（或「用 AI 探测」）
2. 点 **从正文抽取 URL**（探测成功时也会自动预填）
3. 确认列表后 **保存快照**；即使 URL 栏留空，服务端也会在保存时尝试抽取
4. 打开 **引用域名**：应看到对应域名聚合

### 8d) C+ AI 标注建议

1. 需已配置「AI 能力配置」API Key  
2. 粘贴一段提及品牌/竞品的回答 → 点 **AI 标注建议**  
3. 预期：提及勾选、竞品、我方位置、情感、引用 URL 被预填；**尚未写库**  
4. 人工确认或修改后 **保存快照** → 竞品分析 / 评价分析更新  
5. 「用 AI 探测」成功时也应带回上述建议字段  

### 8e) 期次对比（可见度 + 拓词）

1. `alembic upgrade head`（含 `0050_geo_expand_runs`）
2. **GEO 概览**：调整 before/after 时间窗 → **计算 Δ**；两侧无样本时显示「未测」
3. **提问监控**：点两次「拓词」；第二次提示「相对上次 +N」，表内出现「新↑ / 仍在」
4. 拓词持久化**不会**自动入库；仍须勾选后「写入问题库」

> 阶段验收应从 M1 开始（见 `docs/GEO_STAGE_ACCEPTANCE.md`）。Phase 2 发布连接器最后做。

### 9) 发布渠道账号 + 可发布证据（Wave C 收尾）

1. migration 到 `0044_geo_fact_expiry`
2. 侧栏 **发布渠道配置**：首次打开会初始化官网/文档/公众号/知乎/百家号/头条/行业媒体
3. 添加渠道账号并粘贴凭证 JSON → 列表仅显示「已配置凭证」，不回显明文
4. **事实库**：可为事实设置过期日；发布前需核验（verified）且未过期，否则规则 `evidence_publishable` / 回填门禁会拦截
5. HTTP smoke：

```bash
API_KEY=geo-demo-local-key TENANT_ID=1 BASE=http://127.0.0.1:8011 \
  bash scripts/smoke_geo_wave_c.sh
```

## 常见 404

| 错误打开 | 原因 |
| --- | --- |
| `5175/diagnostic-center/` | 诊断中心在 **5174**；5175 若仍是旧静态服务则无此路径 |
| `5176/dashboard.html`（无 `/geo/`） | 正确路径带 `/geo/` |
| `5176/geo/...` 但 API Failed to fetch | 确认 8011 已起，或 URL 带 `api_origin=http://127.0.0.1:8011` |

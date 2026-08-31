# GEO v2 严格对齐验收

日期：2026-08-30。工作树：`geo-prototype-closure-impl`。未提交、未推送。

## 自动化

| 项 | 结果 |
| --- | --- |
| `pytest -q` | 412 passed |
| `cd frontend && node --test tests/*.test.mjs` | 50 passed |
| `cd frontend && npm run build` | exit 0（既有 `@vueuse` annotation 警告，非本轮引入） |
| `git diff --check` | 无本轮空白错误；`app/main.py` 末尾空行警告为既有改动 |

## 本轮补齐的契约与页面

- 路由：`/geo/import`、`/geo/articles/:taskId/distribution`；`/geo/publishing-channels` 与 `/geo/publishing` 重定向到 `/geo/channels`。
- 文章工作台：列改为文章 / 目标提问 / 适配引擎 / AI 友好度 / 状态 / 发布信源；Tab 全部 / 草稿 / 待润色 / 待发布 / 已发布；创建含导入已有文章。
- 编辑器：复制内容、手动发布、自动发布、GEO 评分、保存；一键优化全部 / 分段优化走真实 `/optimize`。
- 分发平台不再做任务推送；分发记录页负责推送草稿、发布、Webhook、URL 回填。
- 提问管理（`/geo/prompts`）CSV 一次导入；可见度页刷新检测走巡检，快照区支持探测回答 / 提取 URL / 检查引用。

## 浏览器抽查（127.0.0.1:5173，客户「泉衡泵业」）

| 路由 | H1 / 关键控件 | 结果 |
| --- | --- | --- |
| `/geo/articles` | GEO 文章；创建；分发记录；工作台列 | 可访问，表格为真实任务 |
| `/geo/articles/26/distribution` | 分发记录 | 可访问 |
| `/geo/articles/26` | 在线编辑器；手动/自动发布；GEO评分 | 可访问 |
| `/geo/channels` | 分发平台 | 可访问 |

未做：17 路由逐页 1440×900 与 D 盘原型 HTML 截图对比；导入→评分→优化→恢复→推送的完整租户闭环（受第三方账号/巡检凭证限制）。

## 仍受环境限制

- 自动发布 / Webhook 需要已配置的渠道账号。
- 探测回答需要租户 AI Key。
- 本地 `--reload` 在 Windows 上可能未热加载；若 Tab 计数仍为 0，重启 uvicorn 后再看 `workbench_counts`。

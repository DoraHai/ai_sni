# GEO 报告 V1：数据与部署口径

本功能使用 `geo_prompts`、`geo_answer_snapshots`、`geo_content_tasks`、`geo_channel_variants`、`geo_publications` 和现有 GEO 项目、业务记录。没有新增表、列或迁移。项目报告章节顺序、显隐和标题保存在 `geo_projects.project_settings.geo_report_template`，恢复默认会删除这一键。GEO 专用迁移链是已退役的分叉；本功能没有依赖它的新迁移。GEO 部署工作流仍不执行迁移。

## 入口与权限

独立 GEO 前端的 `#/geo/report` 提供时间范围、业务筛选、项目模板、趋势、发布 URL 引用、批量导入和下载。`/api/v1/geo/reports/*` 按 `geo.content` 权限检查：GET 需 view，POST/PUT 需 edit；所有请求还检查租户和 GEO 模块授权。Excel/PDF 使用 RFC 5987 下载文件名与 `Cache-Control: private, no-store`。最多导入 500 行、2 MB，预检返回逐行中文错误；确认时重新校验并逐行通过现有 `_write_publication` 的发布审校门槛。导入只登记链接，不访问第三方页面。

`GeoProject` 与 `GeoPrompt` / `GeoContentTask` 没有直接外键。项目选择仅用于客户版名称与模板；数据范围按租户全量或 `business_id` 所指优化业务筛选。UI 明示这一范围，不把业务数据暗称为项目专属。

## 计算口径

- 时间按 `Asia/Shanghai` 日历日；无时区的数据库快照时间按现有约定视作 UTC。周为 ISO 周，月为自然月。每桶提及率为提及条数除以样本条数，零样本率为 `null`，页面显示“无数据”。品牌探测题不计入可见性提及率。
- 主指标默认只统计 `sample_mode=openai_compat`、非模拟且关联服务器巡检 `patrol_run_id` 的真实引擎样本。`manual` 显示“人工录入”，`mock_persona` 或 `simulated=true` 显示“模拟/演示”；`openai_compat` 但没有巡检关联的单次探测草稿可经人工 POST 保存，无法独立证明执行来源，显示“来源未知”。原有 `sample_provenance` 可由历史 note 推断初步类别，但 note 也可由操作员编辑，因此报告要求巡检关联才标记真实，不改写历史快照。各来源分别出现在 Excel 和筛选项中，不进入真实样本主指标。
- 发布 URL 与 `cited_urls` 规范化后完全相等是精准匹配：scheme/host 小写，删除默认端口、尾斜杠、片段和 `utm_*`、`spm`、`from` 参数。保留其他查询参数。相同注册域且路径前缀、同主机域名匹配，或答案文本直接出现 URL，均为待核对的宽松匹配。样本 ID、引擎、日期与被引 URL 逐条列出。零样本时不产生引用证据。
- Excel 含样本明细、日/周/月提及率、发布 URL 引用汇总。问题 × 已配置/已采样引擎 × 日期中无样本的单元留空；多次采样各占一行。所有文本单元格做公式前缀防护。PDF 使用相同范围的服务端快照，附录只列前 100 条，完整记录在 Excel。
- Excel 明细预计超过 25 万行时明确返回 413，请缩短时间或按业务筛选，不生成被静默截断的文件。宽松匹配的注册域使用常见国家域名后缀的保守规则；特殊公共后缀仍需人工核对。

## PDF 运行环境

GEO 采用独立的 `app/geo/report_pdf.py`：Playwright Chromium 无脚本、离线、阻断非 `data:` URL 请求、并发上限 2、超时，A4 页脚显示页码。可设置 `GEO_REPORT_BROWSER_EXECUTABLE_PATH` 或 `GEO_REPORT_BROWSER_CHANNEL`；服务器需安装 Chromium（`playwright install chromium`）和 `fonts-noto-cjk`。当前 `production-geo-deploy.yml` 不安装这两项，缺失时 PDF 接口返回中文 503；Excel 不依赖浏览器。此渲染器与 SEO 分支 `feat/seo-page-capture-v2` 的 `app/seo_monthly_report.render_report_pdf` 功能重复，分支合并时应统一。

示例命令：`python -m scripts.generate_geo_report_sample <输出目录>`。脚本只构造假数据，生成 `sample-geo-report.xlsx` 和 `sample-geo-report.pdf`；使用本机 Chrome 路径存在时优先调用该程序。每个可见名称以“【示例数据】”开头，PDF 每页页脚与 Excel 每张表首行另标“示例数据”。

CI 的 `ops/run_geo_checks.py` 自动发现 `tests/test_geo*.py`；两个 GEO 工作流均调用它。前端由独立 GEO 目录执行 `npm run build`，测试命令为共享前端目录的 `node --test tests/geo*.test.mjs`。

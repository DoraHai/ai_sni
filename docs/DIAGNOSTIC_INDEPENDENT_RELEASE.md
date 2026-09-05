# 诊断中心独立发布

诊断服务从 codex/diagnostic-independent-service 分支开始维护，独立提交与发布。
GEO 生产分支的发布不会替换下列诊断目录、进程和 API 路由。

- API：app.diagnostic_main:app，127.0.0.1:8012，/api/v1/diagnostic/
- 业务代码：app/diagnostic/，不导入 GEO 路由、后台任务或调度器
- 服务：diagnostic-service
- 发布目录：/opt/diagnostic-service/releases/<UTC 时间戳>
- 当前后端：/opt/diagnostic-service/current
- 当前前端：/opt/diagnostic-center/dist，指向同版发布的 frontend
- Nginx：/etc/nginx/snippets/diagnostic-api.conf，直接由门户 HTTPS server 引用
- 日志：journalctl -u diagnostic-service

数据库沿用 geo_audit_runs 和 tenant_memories，保持历史报告 ID 和品牌档案。
登录沿用现有 JWT 与 geo.diagnosis 权限；跨租户请求仍拒绝。
创建 GEO 内容任务是显式跨模块操作，仍请求 GEO 的 content-tasks/from-diagnosis。
第三方官网拒绝抓取（403）不因服务拆分而消失。

首次配置：把 deploy 文件夹和 scripts/bootstrap_diagnostic.sh 上传到服务器暂存目录，
由管理员执行 bootstrap_diagnostic.sh <暂存目录>。它快照现有 Python 环境、
数据库/登录配置与 AI 配置到诊断专属目录，并保留站长 API 暂停状态。
配置文件不进入仓库。后续密钥轮换需同步诊断服务自己的配置。
数据库共享，因此数据库 schema 变更仍须兼容两个服务。

每次发布：

    bash scripts/deploy_diagnostic.sh

该脚本构建诊断前端，上传后端快照与前端，先验证独立 API/数据库健康，再切换前端。
不会运行 Alembic，不重启 GEO/SEM/SEO；失败自动恢复上一个后端与前端。
生产安装依赖后续使用 /opt/diagnostic-service/.venv/bin/python -m pip，
不要调用首次快照中仍可能带有旧 shebang 的 pip/uvicorn 可执行文件。

手动回滚：将 /opt/diagnostic-service/current 与 /opt/diagnostic-center/dist
分别切回发布输出的 previous_backend / previous_frontend，再仅重启 diagnostic-service。
首次迁移的旧前端目录保存在 /opt/diagnostic-center/releases/pre-independent-<时间戳>。

后续不要从旧 GEO checkout 执行旧诊断部署脚本。诊断发布必须使用本分支的新脚本。

## 首次生产切换记录（2026-09-05）

- 发布目录：/opt/diagnostic-service/releases/20260905T133426Z
- 已验证：数据库健康、带鉴权的档案/历史/知识库读取、品牌识别路由、公网 API 与前端入口
- GEO/SEM 进程号和启动时间在切换前后保持不变
- 上一前端：/opt/diagnostic-center/releases/20260818T201048Z-verified-ui
- Nginx 备份：/etc/nginx/conf.d/gsnipers.conf.pre-diagnostic-20260905T133419Z
- 站长 API 仍按原生产配置保持暂停；此次没有消耗站长 API 额度
- 可用 scripts/smoke_diagnostic.py 在服务器再次做只读验收；不会输出凭据或客户资料

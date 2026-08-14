# SEM 智投平台新窗口交接说明

> 更新时间：2026-08-14
> 当前仓库：`D:\workspace\sem`
> 当前分支：`codex/handoff-sem-20260813`
> 当前提交：`25f2780ff04fc12a28b3482fce72870f83f86146`

## 1. 当前接手边界

当前阶段只允许操作 SEM 相关功能。未经负责人明确授权，禁止修改或部署：

- 官网门户
- 旧 Strapi
- GEO 前端
- GEO 服务
- SEO 基线
- 数据库迁移
- Nginx
- 生产环境变量
- 其他非 SEM 模块

即使代码在同一仓库内，也必须保持模块边界，不得为了 SEM 需求顺手改动其他发布单元。

## 2. 安全和权限规则

- 不直接在 `main` 分支开发。
- 每项需求单独建立 `codex/` 开头的功能分支。
- 登录页、SEM 前端、SEM 后端、GEO 前端和 GEO 服务是独立部署单元，禁止互相覆盖。
- 生产部署前必须先确认涉及服务、测试结果、构建结果、数据库变更和回滚方式。
- 数据库迁移、删除生产数据、百度推广真实写回、修改 Nginx、重启生产服务、修改生产 `.env`，都必须提前获得负责人明确授权。
- 不得把服务器密码、SSH 私钥、百度 OAuth SecretKey、数据库密码、Token 或其他密钥提交到 Git 或显示在对话中。
- `deploy/servers.local.json` 只允许本地读取使用，不得提交 GitHub。

## 3. 百度接口文档

本地百度营销商业开发者中心离线文档：

`D:\workspace\sem-doc\baidu-dev-docs-markdown-20260611`

快照信息：

- 抓取时间：2026-06-11
- 页面数量：1037
- 核心文件：`README.md`、`all.md`、`catalog.json`、`pages/`

后续开发百度接口时，优先使用该离线文档定位接口、字段、QPS 限制和错误码。涉及 OAuth、权限范围、调用频次、写操作或已下线接口时，必须再次核对百度官方在线文档。

禁止在文档目录中添加 SecretKey、Token、客户账户凭据或生产环境配置。

## 4. 百度写回状态

当前生产环境处于“不真实写回百度”的演练模式。

除非负责人明确说明开启真实写回，否则：

- 不得修改写回开关；
- 不得执行真实百度推广写操作；
- 不得以部署、调试或验收为由绕过该限制。

## 5. 本地验证状态

已完成：

- SEM 主前端构建通过；
- SEM 构建契约检查通过，检查 47 个 JavaScript assets；
- 独立登录页构建通过；
- 登录页构建契约检查通过；
- 诊断中心构建通过；
- GEO 独立前端构建通过；
- Alembic 单一 head 确认：`0057_seo_rewrite_workflow`。

后端完整测试未能在当前 Windows 环境复跑通过，原因是 `app/scheduler.py` 依赖 Linux 专有模块 `fcntl`，pytest 收集阶段失败。CI/生产环境应在 Linux 下复跑。

## 6. 生产试部署记录

已完成一次 SEM 主前端试部署。

部署范围：

- 只部署 SEM 主前端；
- 未部署独立登录页；
- 未部署 SEM 后端；
- 未部署 GEO；
- 未部署官网；
- 未执行数据库迁移；
- 未修改数据库。

部署版本：

- 新版本：`/opt/sem-frontend/releases/20260813T143351Z`
- 当前 active：`/opt/sem-frontend/releases/20260813T143351Z`
- 上一版本：`/opt/sem-frontend/releases/20260809T161643Z`

部署后验证：

- `https://sem.snipers.com.cn/health` 返回 `env=prod, db=ok`
- `https://sem.snipers.com.cn/onboarding` 返回 HTTP 200
- `https://sem.snipers.com.cn/login` 返回 HTTP 200
- `sem-backend` active
- `geo-service` active
- Nginx 配置检查通过

登录页没有被覆盖，仍保持独立旧版本。

回滚方式：

```bash
ln -sfn /opt/sem-frontend/releases/20260809T161643Z /opt/sem-frontend/current.next
mv -Tf /opt/sem-frontend/current.next /opt/sem-frontend/current
```

## 7. 本地文件状态提醒

当前有文档改动和本地配置文件：

- `HANDOVER.md`：已补充接手边界、百度离线文档、百度写回演练模式规则。
- `LOCAL_SERVER_CONFIG_TEMPLATE.md`：本地服务器配置交接模板。
- `deploy/servers.local.json`：本地服务器连接配置，敏感文件，禁止提交。
- `deploy/servers.local.json.bak-20260813215542`：本地备份文件，禁止提交。

业务代码未改动。

## 8. 下一步建议

新窗口继续开发时，先确认具体 SEM 需求范围，然后：

1. 从当前分支创建新的 `codex/` 功能分支；
2. 只修改 SEM 相关代码；
3. 本地跑对应构建和契约检查；
4. 如果涉及后端，优先在 Linux/CI 环境跑完整 pytest；
5. 如需生产部署，先汇报涉及服务、测试构建结果、数据库变更和回滚方式；
6. 得到明确授权后再部署。

## 9. 服务器连接与 SEM 部署方式（给下一位 AI）

服务器连接配置仅允许从本地文件读取：

- `D:\workspace\sem\deploy\servers.local.json`

该文件是敏感本地配置，禁止提交、禁止贴全文、禁止打印其中密码/Token/私钥/数据库口令。
当前 SEM 生产主机使用 `newApplicationServer` 配置；SSH key 路径以该 JSON 中 `keyPath`
为准。连接时只使用配置值，不在回答中展开密钥内容。

常用生产路径：

- SEM 后端：`/opt/sem-backend`
- SEM 后端服务：`sem-backend`
- SEM 主前端 current：`/opt/sem-frontend/current`
- SEM 主前端 releases：`/opt/sem-frontend/releases/<timestamp>-<desc>`
- 后端健康检查：`curl -fsS http://127.0.0.1:8000/health`

### 9.1 只部署 SEM 后端文件

适用于只改 `app/...` 下 SEM 后端代码、且不涉及迁移时。

本地先跑：

```powershell
.venv\Scripts\python.exe -m py_compile app\path\to\file.py
```

上传和部署模板：

```powershell
scp -i "<keyPath-from-servers.local.json>" app/path/to/file.py root@<sem-host>:/tmp/
ssh -i "<keyPath-from-servers.local.json>" root@<sem-host> 'set -e; cp /tmp/file.py /opt/sem-backend/app/path/to/file.py; rm -f /tmp/file.py; cd /opt/sem-backend; sudo -u sem PYTHONPATH=. .venv/bin/python -m py_compile app/path/to/file.py; systemctl restart sem-backend; sleep 5; systemctl is-active sem-backend; curl -fsS http://127.0.0.1:8000/health'
```

最近一次示例：只部署 `app/classification.py` 和 `app/api/keywords.py`，重启
`sem-backend`，健康检查返回 `{"service":"sem-backend","env":"prod","db":"ok"}`。

### 9.2 部署 SEM 主前端

适用于只改 `frontend/src/...` 的 SEM 主 SPA。不要部署登录页、GEO、官网。

本地先跑：

```powershell
cd D:\workspace\sem\frontend
npm.cmd run build
npm.cmd run verify:sem-build
```

打包和发布模板：

```powershell
cd D:\workspace\sem
$ts=(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
tar -czf "sem-frontend-$ts.tgz" -C frontend/dist .
scp -i "<keyPath-from-servers.local.json>" "sem-frontend-$ts.tgz" root@<sem-host>:/tmp/
ssh -i "<keyPath-from-servers.local.json>" root@<sem-host> 'set -e; release=/opt/sem-frontend/releases/<timestamp>-<desc>; mkdir -p "$release"; tar -xzf /tmp/<package>.tgz -C "$release"; ln -sfn "$release" /opt/sem-frontend/current; rm -f /tmp/<package>.tgz; readlink -f /opt/sem-frontend/current'
Remove-Item -LiteralPath "sem-frontend-$ts.tgz" -ErrorAction SilentlyContinue
```

发布后可用 `readlink -f /opt/sem-frontend/current` 确认 current 指向，用
`ls /opt/sem-frontend/current/assets/<ViewName>-*.js` 确认目标页面资源存在。

### 9.3 执行 Alembic 迁移

迁移必须单独得到负责人明确授权。执行前先贴迁移文件给负责人确认；生产执行前至少确认
当前版本：

```bash
cd /opt/sem-backend
sudo -u sem PYTHONPATH=. .venv/bin/alembic current
sudo -u sem PYTHONPATH=. .venv/bin/alembic upgrade head
systemctl restart sem-backend
curl -fsS http://127.0.0.1:8000/health
```

近期已执行到：`0061_search_term_conversions (head)`。

### 9.4 明确禁区

除非负责人逐项明确授权，否则不要：

- 修改或部署官网、旧 Strapi、GEO、SEO 基线、登录页；
- 修改 Nginx；
- 修改生产 `.env`；
- 执行数据库迁移；
- 打印或提交任何服务器连接密钥、数据库密码、百度 SecretKey、Token；
- 开启百度真实写回。当前百度写回仍为 dry-run 演练模式。

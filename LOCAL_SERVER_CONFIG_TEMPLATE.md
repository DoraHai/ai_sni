# SEM 智投平台服务器配置交接模板

> 用途：本文件仅用于本地填写接手所需的服务器、域名、数据库和第三方平台配置线索。
> 不要填写明文密码、SSH 私钥、数据库密码、百度 OAuth SecretKey、Token 或任何生产密钥。
> 真实密钥请只放在密码管理器或服务器受控环境变量中。

## 1. 基础信息

| 项 | 值 |
| --- | --- |
| 生产域名 | `https://sem.snipers.com.cn` |
| 代码仓库 | `https://github.com/DoraHai/ai_sni.git` |
| 接手分支 | `codex/handoff-sem-20260813` |
| 当前负责人 | 待填写 |
| 运维负责人 | 待填写 |
| 数据库负责人 | 待填写 |
| 百度平台负责人 | 待填写 |

## 2. 服务器访问

| 项 | 值 |
| --- | --- |
| 云厂商 / 区域 | 待填写 |
| 生产服务器公网地址 | 待填写 |
| 生产服务器内网地址 | 待填写 |
| SSH 登录用户 | 待填写，建议独立账号 |
| SSH 登录方式 | 待填写，如密钥 / 堡垒机 |
| 是否允许 sudo | 待填写 |
| 日志查看权限 | 待填写 |
| systemd 操作权限 | 待填写 |
| Nginx 查看权限 | 待填写 |
| Nginx 修改权限 | 待填写，需单独授权 |

## 3. 生产路径与服务

| 发布单元 | 生产路径 / 服务 | 说明 |
| --- | --- | --- |
| SEM 后端 | `/opt/sem-backend` / `sem-backend.service` | FastAPI 主后端，端口 `8000` |
| SEM 主前端 | `/opt/sem-frontend/current` | 独立发布，不得覆盖登录页 |
| 独立登录页 | `/opt/auth-frontend/current` | `/login` 与 `/auth-assets/*` |
| 诊断中心 | `/opt/diagnostic-center/dist` | 独立静态前端 |
| GEO API | `/opt/geo-service/current` / `geo-service.service` | 独立 API，端口 `8010` |
| GEO 前端 | `/opt/geo-frontend/current` | `/deal-sniper/geo/*` |

## 4. Nginx 与域名

| 项 | 值 |
| --- | --- |
| 主域名 | `sem.snipers.com.cn` |
| DNS 管理入口 | 待填写 |
| SSL 证书来源 | 待填写 |
| Nginx 主配置路径 | 待填写 |
| GEO routes include 路径 | 待填写 |
| 访问日志路径 | 待填写 |
| 错误日志路径 | 待填写 |

必须确认：

- `/login` 指向 `/opt/auth-frontend/current`
- `/assets/*` 指向 `/opt/sem-frontend/current`
- `/api/*` 代理到 `127.0.0.1:8000`
- `/api/oauth/baidu/callback` 公开可达
- `/api/v1/geo/*` 代理到 `127.0.0.1:8010`
- `/geo-health` 代理到 GEO 健康检查
- Nginx 不注入 `X-API-Key`

## 5. 数据库

| 项 | 值 |
| --- | --- |
| 数据库类型 | PostgreSQL |
| 数据库版本 | 待填写 |
| 数据库所在平台 | 待填写，如 RDS / 自建 |
| 数据库名 | 待填写 |
| 应用账号 | 待填写，不写密码 |
| 只读账号 | 待填写，不写密码 |
| 迁移账号 | 待填写，不写密码，需发布前单独授权 |
| 备份方式 | 待填写，快照 / `pg_dump` |
| 备份保留策略 | 待填写 |
| 恢复演练记录 | 待填写 |

发布前必须确认：

- 已完成数据库备份或快照
- `alembic heads` 为单一 head
- `alembic current` 符合预期
- 本次是否包含迁移已明确说明
- 迁移失败时的恢复方案已确认

## 6. 生产环境变量位置

| 项 | 值 |
| --- | --- |
| `.env` 路径 | `/opt/sem-backend/.env` |
| 使用该 `.env` 的服务 | `sem-backend.service`、`geo-service.service` |
| 密钥管理器入口 | 待填写 |
| `.env` 文件 owner/group | 待填写，建议 `sem:sem` |
| `.env` 文件权限 | 待填写，建议 `600` |

只记录变量是否存在，不记录真实值：

| 变量 | 状态 |
| --- | --- |
| `APP_ENV` | 待确认 |
| `APP_BASE_URL` | 待确认 |
| `DATABASE_URL` | 待确认 |
| `JWT_SECRET` | 待确认 |
| `ADMIN_API_KEY` | 待确认 |
| `CRYPTO_MASTER_KEY_B64` | 待确认 |
| `BAIDU_APP_ID` | 待确认 |
| `BAIDU_SECRET_KEY` | 待确认 |
| `BAIDU_OAUTH_SCOPE` | 待确认 |
| `DASHSCOPE_API_KEY` | 待确认 |
| `DEEPSEEK_API_KEY` | 待确认 |
| `CHINAZ_*` | 待确认 |
| `PAGESPEED_API_KEY` | 待确认 |

## 7. 百度平台

| 项 | 值 |
| --- | --- |
| 百度营销商业开发者中心账号 | 待填写，不写密码 |
| 服务商应用名称 | 待填写 |
| 应用 ID 是否已配置 | 待确认 |
| SecretKey 是否在密码管理器 | 待确认 |
| OAuth scope 是否已确认 | 待确认 |
| OAuth 回调地址 | `https://sem.snipers.com.cn/api/oauth/baidu/callback` |
| 测试授权账号 | 待填写，不写密码 |
| 生产授权账号管理人 | 待填写 |

## 8. 发布权限红线

以下操作必须提前获得负责人明确授权：

- 生产部署
- 数据库迁移
- 删除生产数据
- 百度推广写回
- 修改 Nginx
- 重启生产服务
- 修改生产 `.env`
- 回滚生产版本

## 9. 首次部署前确认单

| 检查项 | 结果 |
| --- | --- |
| 当前分支不是 `main` | 待确认 |
| 本次功能分支以 `codex/` 开头 | 待确认 |
| 后端测试已通过 | 待确认 |
| Alembic 单一 head | 待确认 |
| SEM 主前端构建通过 | 待确认 |
| 登录页构建通过 | 待确认 |
| 诊断中心构建通过 | 待确认 |
| GEO 前端构建通过 | 待确认 |
| 本次涉及服务已列明 | 待确认 |
| 是否包含数据库变更已列明 | 待确认 |
| 回滚方式已列明 | 待确认 |
| 已获得生产部署明确授权 | 待确认 |

## 10. 部署后验证清单

| 检查项 | 期望 |
| --- | --- |
| `https://sem.snipers.com.cn/health` | SEM 后端健康，数据库正常 |
| `https://sem.snipers.com.cn/geo-health` | GEO API 健康，数据库正常 |
| `https://sem.snipers.com.cn/login` | 登录页可访问 |
| `https://sem.snipers.com.cn/onboarding` | SEM 主前端路由可访问 |
| 百度 OAuth 回调 | 公开可达，缺参数可返回业务错误 |
| `sem-backend.service` | active |
| `geo-service.service` | active |
| Nginx 配置 | `nginx -t` 通过 |
| SEM 页面抽测 | 待填写 |
| 登录与租户切换 | 待填写 |
| GEO 页面抽测 | 待填写 |
| 数据同步状态 | 待填写 |

## 11. 回滚记录模板

| 项 | 值 |
| --- | --- |
| 回滚触发原因 | 待填写 |
| 回滚服务 | 待填写 |
| 回滚前版本 | 待填写 |
| 回滚目标版本 | 待填写 |
| 数据库是否需要恢复 | 待填写 |
| 执行人 | 待填写 |
| 验证结果 | 待填写 |


# 部署到阿里云 ECS（CentOS Stream 9）操作清单

## 前置条件
- ECS 公网 IP：101.200.193.83
- 域名 `sem.snipers.com.cn` 已 A 记录到该 IP
- RDS PostgreSQL 已建好账号 `sem_app` / 库 `sem_prod`，白名单加了 ECS 内网 IP `172.24.244.28`
- 本地代码在 `/Users/daisy/workspace/workspace_ai/ai_sni/`

## 一、初始化服务器（在 ECS 上执行一次）

```bash
# 本地把脚本传上去
scp deploy/setup-centos.sh root@101.200.193.83:/root/

# 登服务器跑
ssh root@101.200.193.83
bash /root/setup-centos.sh
```

## 二、上传代码

```bash
# 本地
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude 'postgres_data' \
  --exclude '.env' --exclude '.git' \
  /Users/daisy/workspace/workspace_ai/ai_sni/ \
  root@101.200.193.83:/opt/sem-backend/

# 服务器
ssh root@101.200.193.83
chown -R sem:sem /opt/sem-backend
```

## 三、配置 .env（在服务器上）

```bash
sudo -u sem bash
cd /opt/sem-backend
cp .env.example .env
vim .env
```

填好这几个值：
- `DATABASE_URL=postgresql+asyncpg://sem_app:<密码>@<RDS 内网地址>:5432/sem_prod`
- `BAIDU_CLIENT_SECRET=<百度应用密钥>`
- `CRYPTO_MASTER_KEY_B64=<本地生成的 32 字节 base64>`

生成主密钥（本地跑一次，结果填进服务器 .env）：
```bash
python3 -c 'import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())'
```

## 四、装依赖 + 跑迁移

```bash
# 仍在 sem 用户下
cd /opt/sem-backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 跑数据库迁移（建表）
alembic upgrade head

# 手动跑一次，确认能起来
uvicorn app.main:app --host 127.0.0.1 --port 8000
# 另开窗口测：curl http://127.0.0.1:8000/health
# Ctrl+C 停掉
exit  # 退出 sem 用户
```

## 五、配 Nginx + HTTPS

```bash
# root 用户
cp /opt/sem-backend/deploy/nginx.conf /etc/nginx/conf.d/sem.conf

# 先注释掉 nginx.conf 里 443 整个 server 块（证书还没签），让 certbot 自己加
# 或者直接：
mkdir -p /var/www/letsencrypt
nginx -t && systemctl enable --now nginx

# 签证书（会自动改 nginx 配置加 443）
certbot --nginx -d sem.snipers.com.cn -m kouhaixia0322@gmail.com --agree-tos -n

# 证书自动续期已经被 certbot 注册成 systemd timer，确认下
systemctl list-timers | grep certbot
```

## 六、注册 systemd 服务

```bash
cp /opt/sem-backend/deploy/sem-backend.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sem-backend
systemctl status sem-backend

# 看日志
tail -f /var/log/sem-backend/stdout.log
```

## 七、分别发布公共登录页与 SEM 主前端

公共登录页已从 SEM SPA 拆出，两者必须分别发布：

```bash
cd /Users/daisy/workspace/workspace_ai/ai_sni/frontend
npm run deploy:sem

# 只构建并发布公共登录页，不会改动 SEM：
npm run deploy:login
```

本地联调时分别启动两个端口。SEM 未登录时会自动跳转到 5174，并保留原页面地址：

```bash
npm run dev
npm run dev:auth
```

两个脚本都会执行以下保护：

1. 构建并检查各自的发布契约；SEM 包内出现登录页代码时会立即终止；
2. SEM 上传到 `/opt/sem-frontend/releases/<时间戳>`；
3. 登录页上传到 `/opt/auth-frontend/releases/<时间戳>`；
4. 分别通过各自的 `current` 软链接原子切换；
5. 使用独立发布锁，两个应用互不覆盖。

Nginx 的登录入口和主前端必须使用
`deploy/sem-frontend-location.nginx.conf` 中的配置，指向
`/opt/auth-frontend/current` 与 `/opt/sem-frontend/current`。禁止重新改回共享的
`/opt/sem-frontend/dist`。

## 八、验证

```bash
curl https://sem.snipers.com.cn/health
# 应返回 {"service":"sem-backend","env":"prod","db":"ok",...}
```

## 九、第一次跑服务商 OAuth 授权

1. 在商业开发者中心打开已生效的服务商应用：
   - `BAIDU_APP_ID` 填应用 ID；
   - `BAIDU_SECRET_KEY` 填应用详情中的 SecretKey；
   - `BAIDU_OAUTH_SCOPE` 填“授权链接”中的 `scope` 参数原值。
   SecretKey 只能进入服务器环境变量，不得写入前端或提交 Git。

2. 执行迁移并重启后端：

```bash
cd /opt/sem-backend
alembic upgrade head
systemctl restart sem-backend
```

3. 验证正式回调已公开可达。缺参数时返回 422 属于正常；不能是 Nginx Basic Auth
   的 401，也不能是路由不存在的 404：

```bash
curl -i https://sem.snipers.com.cn/api/oauth/baidu/callback
```

4. 登录 SEM → 首次接入 → 授权与同步 → 选择客户 → 点击“绑定百度推广”。
   用户在百度官方页同意后，系统会验签、换取 Token、查询普通/超管及子账户、
   加密入库，并在后台启动首次同步。

5. 查库确认授权主体与推广账户均已建立：

```sql
SELECT id, tenant_id, master_name, account_type, expires_at, status
FROM baidu_oauth_grants;

SELECT id, tenant_id, baidu_username, baidu_ucid, account_role, expires_at, status
FROM baidu_accounts
WHERE auth_mode = 'oauth';
```

访问令牌到期前由15分钟调度自动刷新；刷新令牌失效后页面会提示重新授权。

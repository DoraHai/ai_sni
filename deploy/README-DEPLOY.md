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

## 七、验证

```bash
curl https://sem.snipers.com.cn/health
# 应返回 {"service":"sem-backend","env":"prod","db":"ok",...}
```

## 八、第一次跑 OAuth 授权

1. 在 RDS 里插一条 tenants 记录（苏尔寿）：
```sql
INSERT INTO tenants (name, strategy, monthly_budget)
VALUES ('苏尔寿', 'lead', 100000.00);
-- 记下返回的 id（应该是 1）
```

2. 浏览器访问：
```
https://sem.snipers.com.cn/api/oauth/baidu/authorize?tenant_id=1&baidu_username=<苏尔寿的百度推广账户用户名>
```

3. 跳到百度授权页 → 登录苏尔寿账号 → 同意授权 → 回跳到 callback → 应返回 JSON `{"status":"ok", ...}`

4. 查 DB 确认：
```sql
SELECT id, tenant_id, baidu_username, expires_at, status FROM baidu_oauth_tokens;
```

至此 P0 OAuth 闭环完成。

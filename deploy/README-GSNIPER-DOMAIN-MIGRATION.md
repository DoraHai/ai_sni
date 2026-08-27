# SEM 主站域名迁移：`sem` → `gsniper`

目标主域名：`https://gsniper.snipers.com.cn`

旧域名 `https://sem.snipers.com.cn` 在兼容期只负责跳转；百度 OAuth 旧回调暂时继续直连后端，
避免商业开发者中心配置尚未生效时中断授权。

## 发布前门禁

1. 本次变更必须来自干净的 Git 提交，禁止直接修改生产 release 目录。
2. 确认 `gsniper.snipers.com.cn` 的 A 记录指向 `101.200.193.83`。
3. 在百度商业开发者中心登记并审核以下新回调：
   `https://gsniper.snipers.com.cn/api/oauth/baidu/callback`。
4. 保留旧回调，直到新域名至少完成一次真实 OAuth 往返验证。
5. 不修改 `BAIDU_WRITE_DRY_RUN`，不触碰真实资金写回配置。

## 迁移顺序

### 1. 签发新域名证书

先把 `deploy/gsniper-http-bootstrap.conf` 安装为临时 HTTP 站点，执行 `nginx -t` 后 reload，
再使用 webroot 签发证书：

```bash
certbot certonly --webroot -w /var/www/letsencrypt \
  -d gsniper.snipers.com.cn -m kouhaixia0322@gmail.com --agree-tos -n
```

证书签发成功后才能安装 `deploy/nginx.conf`。安装完成必须执行 `nginx -t`，通过后才 reload。

### 2. 双域并行验证

生产环境先设置：

```dotenv
APP_BASE_URL=https://gsniper.snipers.com.cn
CORS_ALLOWED_ORIGINS=https://gsniper.snipers.com.cn,https://sem.snipers.com.cn
```

如果单独设置了 `BAIDU_OAUTH_CALLBACK_URL`，同步改成新回调地址。重启后端前先运行生产配置
保护检查；重启只在配置验证通过后进行。

### 3. 验证新域名

至少检查：

- `/login` 能打开并登录；
- `/health` 返回数据库正常；
- SEM、SEO、GEO、诊断中心和平台门户入口均可打开；
- 未登录访问业务页面会跳转到新域名 `/login`；
- 百度 OAuth 发起接口返回的新回调为 `gsniper.snipers.com.cn`；
- 完成一次测试账户 OAuth 往返；
- 旧域名普通页面以 308 跳转到同路径的新域名。

### 4. 结束兼容期

确认访问日志中不再出现必要的旧域名流量后：

1. 从百度控制台删除旧回调；
2. 删除 Nginx 中旧域名 OAuth 回调例外；
3. 将 `CORS_ALLOWED_ORIGINS` 收紧为仅新域名；
4. 旧域名继续保留 308 跳转，至少覆盖已有书签和外部链接的迁移周期。

## 回滚

如果新域名登录、API 或 OAuth 任一关键链路失败：

1. 恢复 `APP_BASE_URL=https://sem.snipers.com.cn`；
2. 恢复旧域名完整站点 Nginx 配置；
3. 执行 `nginx -t` 后 reload，并重启后端加载旧环境变量；
4. 验证旧域名登录、健康检查和 OAuth；
5. 保留故障版本对应 Git 提交，不直接修改任何 release 产物。

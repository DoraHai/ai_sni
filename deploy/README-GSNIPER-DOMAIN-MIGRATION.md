# 平台主域名迁移：`sem` → `gsnipers`

目标主域名：`https://gsnipers.snipers.com.cn`

该域名已经承载官网和文章 CMS，并已有有效 HTTPS 证书。本次迁移是在同一域名下增加平台路由，
不是替换官网：官网继续拥有 `/`，文章后台继续拥有 `/admin`，CMS 继续拥有通用 `/api`。
平台仅接管明确声明的页面路径及 `/api/v1/`、`/api/oauth/`、`/api/baidu/`。

旧域名 `https://sem.snipers.com.cn` 在兼容期只负责同路径跳转；百度 OAuth 旧回调暂时继续
直连后端，避免商业开发者中心配置切换期间中断授权。

## 发布前门禁

1. 本次变更必须来自已合并的干净 Git 提交，禁止直接修改生产 release 目录。
2. 确认 `gsnipers.snipers.com.cn` 的 DNS、现有官网、CMS 和 HTTPS 均正常。
3. 在百度商业开发者中心登记并审核新回调：
   `https://gsnipers.snipers.com.cn/api/oauth/baidu/callback`。
4. 保留旧回调，直到新域名至少完成一次真实 OAuth 往返验证。
5. 不修改 `BAIDU_WRITE_DRY_RUN`，不触碰真实资金写回配置。
6. 对比当前线上与待发布版本的导航和路由，确认平台与官网已有入口均未丢失。

## 迁移顺序

### 1. 安装统一域名配置

先备份现有 Nginx 配置。将 `deploy/gsnipers.conf` 安装为统一域名配置，将
`deploy/nginx.conf` 安装为旧 `sem` 域名兼容配置。不得重新申请或覆盖现有
`gsnipers.snipers.com.cn` 证书。

安装后先执行 `nginx -t`；只有校验通过才能 reload。若校验失败，恢复备份，不能带病切换。

### 2. 双域并行验证

生产环境设置：

```dotenv
APP_BASE_URL=https://gsnipers.snipers.com.cn
CORS_ALLOWED_ORIGINS=https://gsnipers.snipers.com.cn,https://sem.snipers.com.cn
```

如果单独设置了 `BAIDU_OAUTH_CALLBACK_URL`，同步改成新回调地址。重启后端前先运行生产配置
保护检查；重启只在配置验证通过后进行。

### 3. 验证新域名

至少检查：

- 官网 `/`、文章页、`/admin` 和 CMS API 保持正常；
- `/login` 能打开并登录；
- `/health` 返回数据库正常；
- SEM、SEO、GEO、诊断中心和平台门户入口均可打开；
- 未登录访问业务页面会跳转到新域名 `/login`；
- 百度 OAuth 发起接口返回的新回调为 `gsnipers.snipers.com.cn`；
- 完成一次测试账户 OAuth 往返；
- 旧域名普通页面以 308 跳转到同路径的新域名。

### 4. 结束兼容期

确认访问日志中不再出现必要的旧域名流量后：

1. 从百度控制台删除旧回调；
2. 删除 Nginx 中旧域名 OAuth 回调例外；
3. 将 `CORS_ALLOWED_ORIGINS` 收紧为仅新域名；
4. 旧域名继续保留 308 跳转，至少覆盖已有书签和外部链接的迁移周期。

## 回滚

如果官网、CMS、登录、API 或 OAuth 任一关键链路失败：

1. 恢复切换前的 `gsnipers` 和 `sem` Nginx 配置；
2. 恢复 `APP_BASE_URL=https://sem.snipers.com.cn`；
3. 执行 `nginx -t` 后 reload，并重启后端加载旧环境变量；
4. 验证官网、CMS、旧域名登录、健康检查和 OAuth；
5. 保留故障版本对应 Git 提交，不直接修改任何 release 产物。

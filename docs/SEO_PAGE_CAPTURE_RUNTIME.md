# SEO 页面截图运行环境

截图默认关闭。SEO 服务以 `sem` 用户运行，使用 `/opt/sem-backend/.venv/bin/python`；浏览器需要该 venv 中的 Playwright、Chromium 及系统依赖，并需要 `fonts-noto-cjk`。月报 PDF 也使用此 Chromium 运行环境；Debian/Ubuntu 必须安装 `fonts-noto-cjk` 才能正确显示中文，Windows 使用系统自带的 Microsoft YaHei。截图目录必须持久化，且位于 `/opt/seo-service` 发布目录之外。浏览器直连外网应由服务器网络策略阻断；服务会代理并校验 HTTP 资源。

在服务器上以 root 手动运行：

```bash
bash scripts/install_seo_page_capture_runtime.sh --dry-run
bash scripts/install_seo_page_capture_runtime.sh \
  --service-user sem --python /opt/sem-backend/.venv/bin/python \
  --storage-dir /var/lib/seo-service/page-captures
```

脚本可重复运行，不会开启截图功能。可用 `SEO_PAGE_CAPTURE_SERVICE_USER`、`SEO_PAGE_CAPTURE_PYTHON`、`SEO_PAGE_CAPTURE_STORAGE_DIR` 环境变量覆盖参数默认值。生产部署 workflow 只有在仓库变量 `SEO_PAGE_CAPTURE_RUNTIME=install` 时才尝试运行脚本；该可选步骤失败不会中断原部署。服务器受限 sudo 如未允许 `sudo -n bash -s`，需由运维手动以 root 执行。

系统依赖（`playwright install-deps chromium`）以 root 安装；Chromium 本体用 `runuser -u sem` 安装到 `sem` 用户自己的 Playwright 缓存（`~sem/.cache/ms-playwright`），这正是服务（systemd `User=sem`）运行时查找浏览器的位置。不要直接以 root 运行 `playwright install`，否则浏览器会装到 `/root/.cache`，服务找不到。注意 `/opt/sem-backend/.venv` 由 SEM、GEO、SEO 三个服务共用，安装 `requirements.txt` 中的 playwright 会影响这个共用环境。

审核运行环境和目录权限后，在服务配置中设置 `SEO_PAGE_CAPTURE_ENABLED=true`，按需配置 `SEO_PAGE_CAPTURE_STORAGE_DIR`、`SEO_PAGE_CAPTURE_MAX_REDIRECTS`（默认 5）和 `SEO_PAGE_CAPTURE_SETTLE_SECONDS`（默认 3）。`SEO_PAGE_CAPTURE_MAX_REQUESTS` 默认 300、允许 1–500，包含主文档、重定向及重试；`SEO_PAGE_CAPTURE_PER_HOST_CONCURRENCY` 默认 4、允许 1–16，仅限制同一截图内同一主机的子资源请求。子资源遇到 429 或 503 最多重试 2 次；秒数形式的 `Retry-After` 单次最多等待 2 秒，其余情况短暂退避。每次重试及重定向仍重新验证公网地址并做 DNS 钉扎。总耗时仍由 `SEO_PAGE_CAPTURE_TIMEOUT_SECONDS` 限制。

截图结果记录主文档每跳的 URL 与 HTTP 状态。子资源警告保留 `blocked_subresources`、`failed_subresources` 总数，并增加 `by_reason` 原因计数、`hosts`（最多 10 个有问题资源的主机名，不含路径和查询）、`samples`（最多 5 个原因码）。原因包括 `blocked_private`（内网或保留地址）、`blocked_policy`（方法、协议、大小或重定向策略）、`request_limit`、`http_error`、`rate_limited`（429/503 重试耗尽）、`network_failed`、`timeout`、`dns_error` 等。示例：`{"blocked_subresources": 1, "failed_subresources": 1, "by_reason": {"request_limit": 1, "rate_limited": 1}, "hosts": ["media.example.com"], "samples": ["too_many_requests", "rate_limited"]}`。警告中不保存完整子资源 URL。主文档超过总字节上限时截图失败，错误码为 `resources_too_large`；子资源使总量超限时只记警告并中止该资源，后续资源继续被拦截，截图仍可成功。

迁移 `0100_seo_page_captures` 必须单独审核和执行；部署 workflow 不自动迁移数据库。

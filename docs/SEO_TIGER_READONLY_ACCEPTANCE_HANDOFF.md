# Tiger SEO GET-only 验收交接

目标是用已登录、已获授权的会话核对 `tenant_id=4` 的 SEO 生产数据准备情况。工具只发 GET，不包含登录、密码、令牌字面量、建站、采集、生成或发布逻辑。

## 文件

- `scripts/accept_tiger_seo_readonly.py`：生产 GET-only 验收脚本。
- `tests/test_accept_tiger_seo_readonly.py`：空站点、未配 GSC、无内容、无发布、跨租户拒绝和公开抓取来源标签的离线契约。

## 运行方式

人工先用获准账号登录，再通过受控渠道把当前 Bearer 会话放入运行进程的环境变量。不要把令牌放在命令行、脚本、输出文件或聊天里。

```bash
export GSNIPERS_BEARER_TOKEN='<existing authorized browser session token>'
python scripts/accept_tiger_seo_readonly.py \
  --tenant-id 4 \
  --expected-domain tiger-coatings.cn \
  --output tiger-seo-readonly-result.json
unset GSNIPERS_BEARER_TOKEN
```

可选传入已有的公开网页预检文件：

```bash
python scripts/accept_tiger_seo_readonly.py \
  --public-preflight /controlled/path/tiger-public-crawl-20260908.json
```

该部分固定输出 `source=public_preflight` 和 `production_data=false`，不得将它作为生产 SEO 页面库、搜索表现或驾驶舱统计。

## 验收顺序

1. `/api/v1/auth/me`：普通账号必须绑定租户 4；超管允许 `tenant_id=null`。
2. `/api/v1/auth/modules`：SEO 必须 `available=true`。
3. `/api/v1/seo/sites?tenant_id=4` 与 `/api/v1/seo/workbench/sites?tenant_id=4`：按 `canonical_domain=tiger-coatings.cn` 精确匹配。
4. 没有匹配站点时输出 `status=empty_site`，立即停止，不猜 `site_id`。
5. 恰好一个匹配站点时，读取内容、发布、页面、GSC 配置和 cockpit 指标快照，输出 count / coverage / freshness。

空列表只证明该接口可读且当前无对象；不等于所有详情接口通过。`client_non_get_requests=0` 只证明客户端本次没有发送非 GET，不能单独证明服务端的 GET 永远无内部副作用。

## 待审查项

- 生产 SEO 是否仍暴露 `/api/v1/seo/cockpit/metrics/snapshot`；若发布基线改名，只更新确认过的 GET 路径。
- `content-distribution/publications` 目前没有分页参数，验收时会读取该站点全部发布记录；数量过大时应由 SEO 接口增加分页，不应由脚本猜参数。
- GSC 端点只证明连接配置；点击、展示、CTR 和平均排名仍应以指标快照的 source / observed_at / data_quality 为准。
- 单篇文章搜索点击仍不可由站点级 GSC 数据推算。

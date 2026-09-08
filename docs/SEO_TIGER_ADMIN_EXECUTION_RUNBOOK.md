# Tiger SEO 普通账号验收与空站点后续执行单

适用范围固定为生产域 `https://gsnipers.snipers.com.cn`、客户
`tenant_id=4`、官网 `tiger-coatings.cn`。本执行单先完成 GET-only 验收；建站
只是后续申请规范，不代表已授权写入。

## 一、执行前由管理员准备

### 1. 普通账号

使用绑定 `tenant_id=4` 的普通账号。`GET /api/v1/auth/me` 返回的四项权限必须
分别为 `view` 或 `edit`：

| 权限 | 本次用途 |
| --- | --- |
| `seo.assets` | 读取客户已有 SEO 站点 |
| `seo.content` | 读取内容与发布记录 |
| `seo.site` | 读取页面检查数据 |
| `seo.keywords` | 读取 SEO 指标相关数据 |

缺少任一项时不要临时改成超管账号继续跑。由账号管理员修正普通账号权限后重新
执行。脚本拒绝未绑定客户的会话，也不会根据角色名称猜权限。

### 2. 代码与输出目录

使用包含 Tiger harness 的已合并基线：

```text
main commit: 8ba839703d91e7720bf8160b249d61ed3c704ef8
script: scripts/accept_tiger_seo_readonly.py
```

可使用更新的 `main`，但必须先确认该脚本存在，并记录实际执行 SHA。不要在正在
提供线上服务的 release 目录中切换分支；使用已有干净 checkout 或单独 worktree。
输出目录权限应限制为当前执行人可读。

## 二、安全注入会话并执行

人工先在正常登录页面完成登录。Bearer token 通过团队既有凭证渠道交给执行人，
不要贴到聊天、工单、命令行参数、输出 JSON 或 shell 历史。Linux/macOS 可用无回显
输入把 token 只放入当前进程环境：

```bash
cd /path/to/clean/ai_sni-checkout
git rev-parse HEAD
git status --short

umask 077
read -rsp 'GSNIPERS_BEARER_TOKEN: ' GSNIPERS_BEARER_TOKEN
echo
export GSNIPERS_BEARER_TOKEN
python scripts/accept_tiger_seo_readonly.py \
  --output /tmp/tiger-seo-readonly-result.json
acceptance_rc=$?
unset GSNIPERS_BEARER_TOKEN
printf 'exit_code=%s\n' "$acceptance_rc"
sha256sum /tmp/tiger-seo-readonly-result.json 2>/dev/null || true
```

要求：

- `git status --short` 必须为空；记录 `git rev-parse HEAD` 的完整值。
- `read -s` 期间输入不回显。运行完成后立即 `unset`，关闭承载 token 的终端会话。
- 不要使用 `TOKEN=... python ...`、命令行 `--token`、shell 脚本常量或截图传递 token。
- 若退出码不是 `0`，停止，不用管理员 Key 或其他客户会话绕过失败。
- 输出文件按凭证级材料保管；回传摘要后由执行人按团队保留策略清理。

脚本只允许 GET，并固定 origin、tenant 和域名。它会阻止跨域重定向携带
Authorization，也不接受 CLI 改写目标客户或域名。

## 三、预期结果

成功执行退出码为 `0`，JSON 至少满足：

```json
{
  "contract": "tiger-seo-readonly-v1",
  "tenant_id": 4,
  "expected_domain": "tiger-coatings.cn",
  "request_policy": "GET-only",
  "production_mutations": 0,
  "client_non_get_requests": 0
}
```

`client_request_methods` 中每一项都必须是 `GET`。按 `status` 处理：

| status | 含义 | 下一步 |
| --- | --- | --- |
| `readable` | 找到唯一 active 站点且只读端点可读 | 核对各 probe 的 count、coverage、freshness |
| `empty_site` | 客户 4 没有匹配 `tiger-coatings.cn` 的站点对象 | 停止本次验收，进入第五节查重和申请流程 |
| `site_unavailable` | 重复站点、两份列表漂移、暂停/归档或选择策略漂移 | 停止，交 SEO 负责人修正，不创建第二个站点 |
| `seo_module_unavailable` | 当前客户未获得可用 SEO 模块 | 停止，交账号/模块管理员核对 |

脚本以退出码 `2` 失败时，只回传错误类别和发生步骤。不得回传 HTTP
Authorization、token、密码或完整请求头。

## 四、执行人需要回传的字段

将以下摘要发给工作台统筹人和 SEO 负责人：

1. 执行时间与时区、执行机器用途、完整 Git SHA、`git status` 是否干净。
2. 退出码、输出文件 SHA-256、顶层 `status`。
3. `route_contract`。
4. `identity.id`、`identity.tenant_id`、`identity.required_permission_keys`；只需确认
   四项权限通过，不贴 token 或请求头。
5. `module.available`。
6. `sites.stored_count`、`sites.workbench_count`、`sites.selection_policy`、
   `sites.expected_domain_matches`；若存在则回传 `site_id`。
7. 每个 probe 的 `name/count/coverage/freshness`，以及 `states`。
8. `client_request_methods` 和 `client_non_get_requests`。
9. 如使用公开网页预检，只回传其 `source=public_preflight`、
   `production_data=false`、抓取时间和汇总计数。

不要把整个原始响应贴进公开聊天。站点列表明细和模块原始条目仅在受控渠道按需
提供。

## 五、`empty_site` 后的创建前查重

`empty_site` 不是建站授权。先由具备 `seo.assets:view` 的 tenant 4 身份再次执行：

```http
GET /api/v1/seo/sites?tenant_id=4
GET /api/v1/seo/workbench/sites?tenant_id=4
```

查重必须同时满足：

1. 对每个 `domain` 和 `canonical_domain` 做相同规范化：域名转小写、去末尾点、去
   最前面的 `www.`，目标值为 `tiger-coatings.cn`。
2. 两个列表按 `site_id/domain/status` 交叉核对；选择策略必须精确为
   `selectable_statuses=[active]`、`disabled_statuses=[paused, archived]`。
3. 匹配数为 `1`：禁止创建，使用现有站点；若两表不一致则先修复列表契约。
4. 匹配数大于 `1`：禁止创建和删除，提交重复数据核查单。
5. 匹配数为 `0`：记录查重时间和脱敏结果，才可提出创建申请。实际 POST 前由执行人
   再做一次相同 GET，避免并发重复创建。

## 六、站点创建请求规范（待单独审批）

申请单必须包含：

```json
{
  "method": "POST",
  "path": "/api/v1/seo/sites",
  "body": {
    "tenant_id": 4,
    "name": "老虎新材料官网",
    "domain": "https://www.tiger-coatings.cn/"
  },
  "expected": {
    "tenant_id": 4,
    "canonical_domain": "tiger-coatings.cn",
    "status": "active"
  }
}
```

同时写明审批人、执行人、计划时间、执行身份、最近一次查重证据、回滚/停用负责人和
是否允许后续采集。执行身份必须具备 `seo.assets:edit`，并通过客户 4 的 SEO 模块
资格检查。

当前创建接口不接受 `status`，新站会以 `active` 建立。active 站点可能被 SEO 定时
任务选中，因此在 SEO 负责人确认调度范围、并取得“允许创建且允许可能发生的后续
采集”的单独授权前，**不得发送该 POST**。如果本次只允许建对象、不允许采集，应先
由 SEO 开发提供可原子创建为 paused 的受审方案；不要用“POST 后立即 PATCH”模拟
原子操作，因为两次请求之间存在被调度选中的窗口。

获得单独审批并完成创建后，立即用两个 GET 复核唯一 site ID、规范域名和状态，再
重新运行 GET-only harness。不要在同一操作中启动采集、GSC 连接、内容生成、发布或
页面导入。

## 七、本执行单禁止的操作

- 不发送 POST、PUT、PATCH、DELETE；第六节只是未来写操作申请模板。
- 不建站、不改站点状态、不直接改数据库。
- 不启动抓取、排名/GSC 采集、内容生成、发布、页面导入或异步任务。
- 不使用超管身份替代普通账号验收，不跨租户读取。
- 不把公开网页预检当成生产页面库、GSC 数据或获客指标。
- 不根据空列表声称详情接口、搜索点击或发布链路已经通过。

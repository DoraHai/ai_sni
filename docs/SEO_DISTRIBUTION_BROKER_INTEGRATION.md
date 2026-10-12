# SEO 原生来源与中央分发本地联调

2026-10-11，SEO 工作区 `seo-distribution-sources-20261011`，来源基线
`8e7cf488a1617d702d080090ab3a2589e0ec0224`。后续本批追加原生小红书不可变素材，详见 `SEO_DISTRIBUTION_MEDIA.md`。
中央代码由中央工作区负责，本工作区仅动态加载进行联调。

中央代码从同机 `distribution-control-20261011` 通过 importlib 装入原生 `app` 包，
直接使用 SEO models、实名 JWT、当前数据库角色和实际 authorize_scope/list_sources/load_source。
只替换 FastAPI 数据库依赖以接入专用测试库，不 mock 鉴权、来源或 broker。
**具体受测版本以证据 JSON 中中央来源类型、commit 和文件 SHA256 为准**。
设置 `SEO_DISTRIBUTION_ROOT_COMMIT=<40位本地提交>` 后测试通过 git show 读取该提交中的全部中央模块和 DDL，
不受中央工作区后续未提交修改影响；未设置时仅代表工作区文件测试，不能仅凭 HEAD 复现。
本轮同时加载新增 distribution_scheduling 及其独立测试 DDL，不复制或合并中央文件。
本轮最终固定中央提交：`cb305e8580602569485e55588760cfbd94dc67fc`，使用上述 git_commit 模式执行。
受测 SEO 原生代码为干净提交 `6d523672e9b175293469fb7049aaf40a06653b99`；本次版本收尾仅更新文档和证据。

## 结果

19 项中央联调、25 项原生素材测试、1 项真实浏览器流程，与既有 126 项回归合跑共 **171 项通过、0 失败、0 跳过**。
合跑时先加载并卸载中央模块，再运行原生来源/分发/客户确认测试，确认无包命名空间残留影响。
包括以下真实数据库链路：

- 实名顾问 JWT → 当前角色/客户/网站分配 → 可选稿件摘要和准确正文预览。
- 独立管理员 JWT → 创建设备、账号绑定 → 顾问启动项目 → preflight/handoff 入队。
- 独立设备凭证 → exchange 下发，projectId 为 `seo-2`；preflight 回执进入 succeeded，handoff 进入 awaiting-human。
- 正文改变、撤审、取消顾问分配、新增未审版本四种变化，在派发前均使旧任务 canceled；派发后均使旧任务 unknown、revoked，且不再返回旧任务或 grant。
- 撤审、正文改变、取消顾问分配后，即使提交旧 succeeded 回执，也保持 unknown，不接受为成功。
- 匿名、跨客户、跨网站、顾问调用管理员接口及 JWT 签发后降权均被拒绝。
- 原生小红书 PNG/JPEG 上传、独立审核冻结后，实际中央设备端点下载字节与 manifest 摘要一致。
  撤审、换图、取消顾问分配后三种情况，设备无法继续下载，旧 grants 清除；宽松截断模式开启时返回 503。
  独立候选上传/审核页面已用真实 Chromium、JWT、原生数据库验收，未接入共享工作台导航。

其中 2 项为正文长度差异修复回归，分别覆盖普通字符与 UTF-16 字符计数。

## 正文长度差异已由中央列表过滤解决

SEO load_source 目前允许最多 400000 个 Python 字符；中央 ApprovedContent 同时要求正文
不超过 100000 个 Python 字符和 100000 个 UTF-16 code units。
中央 `/sources` 现对原生候选逐一调用真实 core.source / ApprovedContent，
仅提供完整、当前有效且符合执行协议的快照；版本在两次读取间变化也不提供。
原生列表仍保留模块自身合法的长稿，中央列表过滤超限稿件，不截断任何已审正文。

| 回归正文 | 原生列表 | 中央列表 | 直接中央预览 |
| --- | --- | --- | --- |
| `selection ` + 100000 个 ASCII 字符 | 保留 | 过滤 | 409 source_changed |
| `selection ` + 50000 个 emoji | 保留 | 过滤 | 409 source_changed |
| 同范围正常已审稿件 | 保留 | 保留 | 200，正文/版本与原生快照完全一致 |

两项测试均在同一范围同时放入长稿和正常稿，证明中央不会误过滤正常内容；
再次读取数据库确认长稿正文未被修改。原有实名权限、派发与回执失效测试一并合跑。
长正文过滤修复由中央工作区提供；没有改动原生正文长度门槛。

## 执行与证据

- 测试：`tests/test_seo_distribution_broker_postgres.py`；显式设置 `SEO_DISTRIBUTION_INTEGRATION=true`。
- 测试库固定为 loopback `127.0.0.1:55443`，用户 `distribution_test`，库 `distribution_control_test`。
  每项创建随机 `seo_broker_test_<uuid>` schema，结束后清理；只执行本地候选 DDL。
- 环境使用合成配置与数据；HTTP 使用进程内 ASGITransport，真实 HTTP transport 被测试夹具禁止。
- 可版本化证据：`docs/SEO_DISTRIBUTION_BROKER_EVIDENCE.json`，仅包含版本摘要、文件校验值、案例结果，
  不包含 JWT、设备凭证或任何生产资料。
- 原始 XML/运行证据：TEMP 下 `seo-distribution-broker-tests.xml`、`seo-distribution-broker-evidence.json`、
  `seo-distribution-integrated-regression.xml`。

本轮没有注册生产路由、推送、部署、生产迁移、平台发布或覆盖冻结工作区。
未验证共享工作台 UI、HTTPS transport、真实平台登录/上传/发布。preflight 成功也不代表文章已发布或搜索效果已提升。

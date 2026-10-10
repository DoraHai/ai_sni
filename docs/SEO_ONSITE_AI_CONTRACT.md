# SEO 站内 AI 提案与顾问汇总

开发基线：`29b125cbb02b65c24a2c7c8ab55bd7c09047c06f`（origin/codex/production-seo，含 PR633）。
对齐 `AI_WORKFLOW_COORDINATION_20261010.md`。本轮仅后端、本地测试与提交，无生产配置、迁移、采集、发布或官网写入。

## 顾问汇总（只读）

`GET /api/v1/seo/workbench/advisor-tasks?limit=20&tenant_id=4&before_id=100`

- `tenant_id`、`before_id` 可省略；`limit` 默认 20，范围 1–50。
- 响应：`schema=1,module="seo",items,next_before_id`，按任务 ID 降序；下一页严格 ID 小于游标。
- 先用 SQL 联结任务、站点、客户、模块权益、当前 active 顾问分配、有效实名用户和角色，再分页。用户客户绑定、网站启用、模块 active/trial 和到期日均在 SQL 中过滤。无分配/无编辑资格返回空，API Key 无实名身份返回 403。显式越权客户筛选返回 403。
- 每项沿用站内记录，新增 `scope_name,tenant_name,next_action,blocker,capabilities`；blocker 为安全 `{code,message}` 或 null。仅汇总 `onsite_optimization` schema=1，不声称包含所有类型的顾问工单。
- GET 不创建任务、不更新游标或运行状态、不启动生成/采集，也不访问供应商。没有全量统计字段，当前页长度不等于任务总量。

## 手动触发 AI 提案

`POST /api/v1/seo/workbench/onsite-tasks/123/ai-proposal`

```json
{
  "tenant_id": 4,
  "site_id": 2,
  "expected_revision": 1,
  "request_id": "9d4d4214-ce30-4b89-a6d8-cbfa51186ec8",
  "mode": "initial"
}
```

必须为有效实名顾问，拥有本站 active 分配、seo.site/seo.content 编辑权限和 seo.keywords 查看权限，客户绑定匹配且网站与模块启用。接口不接受新增 URL、模型配置、资料 ID 或工具命令。

`initial` 仅 draft；`revise` 允许当前未结束任务，包括复检失败。done/cancelled 拒绝。成功响应沿用站内记录，增加 `replayed`；主要字段示意（非真实客户数据）：

```json
{
  "id": 123, "module": "seo", "tenant_id": 4, "scope_id": 2,
  "workflow": {
    "schema": 1, "revision": 2, "phase": "review",
    "ai_run": {
      "request_id": "9d4d4214-ce30-4b89-a6d8-cbfa51186ec8",
      "state": "ready", "mode": "initial", "source_revision": 1,
      "source_hash": "sha256-of-server-source-bundle", "actor_user_id": 7,
      "started_at": "2026-10-10T08:00:00+00:00", "finished_at": "2026-10-10T08:00:05+00:00"
    },
    "ai_proposal": {
      "summary": "AI 起草，事实和适用条件仍须人工核对；未修改官网",
      "proposal_revision": 2,
      "items": [{"id": "title-10", "reason": "依据公开资料，仍需人工确认", "source_refs": ["fact:30:v1"], "missing_information": []}],
      "missing_information": []
    }
  },
  "allowed_actions": ["save_proposal", "cancel", "approve"],
  "completion_evidence": null,
  "capabilities": {
    "ai_planning": {"enabled": true, "can_generate": true, "reason": null, "daily_limit": 5},
    "website_execution": {"enabled": false, "status": "reserved", "reason": "官网自动修改暂未接入，按批准方案人工实施"}
  },
  "replayed": false
}
```

示例省略原记录的 title、items/source/history 等不变字段；实际 source_hash 是 64 位十六进制。理由与缺项仅在 ai_proposal 内，既有验收 Item 仍只有 id/kind/target_url/expected/instruction。缺证据的项 expected 为空、missing_information 有说明，整体仍待人工补充，不能审核空预期值。

## 有界、幂等与事实边界

- 每网站每天最多 **5 次准入**，北京时间自然日，记录在既有 `SeoSite.site_settings.onsite_ai_quota`。本站多个任务共享配额；成功、失败和不明都保留额度，平台 controls 未启用也生效。没有付费自动重试。
- 每任务最多 **40 个不同请求**，请求台账保存在 `SeoTask.params.onsite_ai_requests`，不删除旧 nonce；仍受原任务 100 条历史上限。无需 DDL。
- 先按客户+UUID 的事务级 advisory lock 去重（跨本站任务及同客户其他网站），再按网站/任务行锁串行保存 nonce、操作者、模式、源版本/哈希、无密钥的供应商地址/模型元数据和 `running`，提交释放事务后才调用供应商。同 nonce 同参数返回已记录状态（replayed=true），不同参数/操作者或跨任务复用 UUID 返回 409，不暴露另一任务资料；旧 nonce 已被后续请求替代返回 409，不再付费。另一 nonce 遇到当前运行返回 409。
- 供应商超时 45 秒，外层 55 秒；一次尝试。崩溃后状态可保留 running，显式重放同请求在 120 秒后将其记为 unknown，绝不重新调用。GET 不负责恢复或偷偷重试。此后顾问核对并使用新 UUID 才是新尝试，仍受配额限制。
- 只使用当前任务绑定的关键词和页面、当前网站最多 20 条有效且有出处的 QA 事实；资料总上下文最多 5 万字符。page/keyword/fact 引用使用服务器提供的 ID/版本，未检查页面不提供伪造的页面事实。
- 保留清单所有 id/kind/target_url；关键词预期须属于绑定词，Meta Keywords 限于该页绑定词；内链/canonical 只能选已绑定页面。新网址、假来源、敏感输出、结构不合规拒绝保存。当前没有 robots/sitemap 文件正文证据，因此这类预期必须留空并列缺项；不能编造文件策略。
- AI 文案是待审核建议，引用有效来源不等于系统证明每句话正确，事实、适用条件和内容质量必须人工确认。只发 JSON 提案，没有网站执行工具。
- 外部调用后重新读取实名用户/角色、顾问分配、模块/网站、任务版本以及来源哈希；最终事务对权限与来源记录加短读锁。撤权、人工修改、资料变更、任务结束或迟到结果均不能覆盖人工状态，记 stale。撤权后错误只回安全描述，不回任务内容。
- 成功通过原 `prepare_change(save_proposal)`，增加 revision、转 review、清除旧审核/实施/复检/验收与 completion_evidence。人工再次保存方案会清除旧 AI 提案说明，避免把理由挂在已修改方案上。

## 供应商与错误

复用现有 `app.ai.deepseek.chat_json`：沿用百炼优先、DeepSeek 后备的配置选择，单次请求不做失败回退，不创建密钥、不换供应商。仅接受现有官方 HTTPS 入口。计量 context 绑定 tenant/user/module=seo/feature；`job_ref=site:{site_id}:onsite_ai_proposal:{task_id}:{request_id}`，底层供应商 operation 仍为既有 `chat.completions`。不修改 metering/controls schema 或开关，不向普通客户/顾问返回供应商成本、密钥或原始错误。

- 401/403：身份、权限、分配不符；404：任务/站点范围不符。
- 409：旧 revision、nonce 冲突、正在运行、已结束、来源变化或迟到结果。
- 422：请求或上下文不符合限制；429：本站当日准入上限；503：未配置可用官方供应商。
- 已完成准入的供应商拒绝记录 failed，超时/解析失败/不合规输出记录 unknown，并用 HTTP 200 返回安全状态，调用方须检查 ai_run.state，不能把 HTTP 200 当作生成成功。

## 本轮未启用与验证

月度自动建单、自动接续、官网自动修改均未启用；不新增计划开关或调度任务。启动/月度/整改由已有人工建单入口创建，再由有权限顾问明确触发 AI。

测试包含纯校验、HTTP 契约及真实 PostgreSQL：跨客户、撤权、角色/客户绑定变化、模块到期、并发 nonce、跨任务日限额、迟到与人工更新、资料变化、供应商失败/未知、复检失败后修订清证据、GET 无写入。PG 使用现有 loopback `seo_workflow_test`、显式 schema-create 授权和每测试随机 schema；供应商替身，不接真实平台。SEO baseline 原生 PG 作业纳入新测试并检查零跳过；常规回归纳入 baseline/deploy，发布白名单仅增加必要精确路径。

# Export 查询/显式登记拆分

独立分支 codex/geo-readiness-export-readonly-20260906；本笔基准0b17259（readiness已单独提交），未推送/部署。共享auth未变，其余15个写GET不在本包。

## 接口与兼容性

- GET /api/v1/geo/content-tasks/{task_id}/export 保持tenant_id/channel及原内容字段，使用GEO资格依赖、view权限和READ ONLY / REPEATABLE READ事务；纯内存渲染缺失HTML，无行锁、状态/元数据更新、初始化、生成模型或发布。返回实际status；未知quality为unknown，不能把下载推断为可发布。
- POST同路径为显式登记，必须geo.content edit及有效GEO资格。JSON要求expected_revision（64位十六进制内容版本摘要），来自任务详情渠道稿或GET预览。获取并刷新任务行锁后，依据当前渠道稿ID/关联母稿/当前最新母稿ID/标题/正文/已保存HTML重新计算，变化409。摘要用于乐观冲突检测，不是授权token。
- POST沿用原exported状态登记、HTML表示缓存、pipeline_step/blocked_reason及prompt.last_task_id同步；不改review_status/reviewed_by，不创建发布记录、不调用采集/模型/发布。published任务和渠道稿不降级，保留publication_monitor/push_deliveries。导出不把delivery=adapted_draft_not_publishable升级，也不默认quality=publish_ready。
- 新POST首次填充HTML后摘要可能变化；重用旧摘要409，客户端需采用刷新后的版本。监测元数据更新不纳入摘要，POST在同一任务锁后读取最新元数据并合并，避免丢失监测历史。
- Vue和静态台显式导出调用POST并提交当前保存的摘要；缺摘要要求刷新。Vue阻止未保存稿件导出，迟到响应不刷新其他客户。原Webhook验收脚本改为只读预览取摘要再POST登记；本轮没有运行其外发流程。
- 旧GET调用仍能获得内容，但不再登记exported；这是刻意的行为修正。旧静态前端调用新API但未携带摘要会422，需前后端一起发布并刷新缓存。客户仍只审核一次，无额外审核流程。

## 验证

- 本机独立PG16.15全量：954 passed、1 skipped（Windows无法运行Linux flock）、1 warning。所有数据库专项实跑；fixture鉴权不替代真实JWT。
- 新真实HTTP/SQL验证：GET在其他连接持有任务写锁时仍完成，读取前后任务/渠道稿/问题/发布表逐字段相同；view POST403、缺摘要422、撤销资格后GET/POST403；edit POST登记且保留审核/监测/发送日志、无发布记录。
- 用pg_blocking_pids确认POST实际等待任务锁；等待期间正文改变或新母稿产生后409，未错误登记旧稿；只有监测变化时可登记且保留最新监测。已published记录导出后仍published。
- 前端147项通过，无跳过；包括真实导出函数保存版本参数、未保存/缺版本不请求、客户切换迟到响应及POST适配。独立GEO前端构建成功，保留已有大包提示。
- GET纯内容不意味着事实已合格；H1及真实发布仍未验收。本笔按负责人复审后再安排发布，测试/文档不单独发布。

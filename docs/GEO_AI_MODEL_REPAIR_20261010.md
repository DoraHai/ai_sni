# GEO AI 模型配置修复 · 2026-10-10

## 已定位的原因

GEO 的 systemd 服务依次加载共享 `/opt/sem-backend/.env` 与独立 `/opt/geo-service/.env`。故障模型值来自 GEO 独立文件：`DASHSCOPE_MODEL=deepseek-v4-flash`，接入地址为百炼兼容接口。

使用同一现有凭证读取该接口模型目录返回 HTTP 200；目录没有 `deepseek-v4-flash`，包含 `deepseek-v4-flash-0731`、`deepseek-v4.1-flash` 等明确版本。原模型生成调用返回 HTTP 404，错误码 `model_not_found`。

未改生产配置的隔离验证中，将模型参数指定为 `deepseek-v4-flash-0731`，沿用原 GEO 凭证与原接入地址，真实客户端成功返回精确 JSON `{"ok":true}`。不需要新增密钥，也不需要修改共享 SEM/SEO 环境。

## 执行范围

用户已要求修复 GEO 配置并开始稳定性开发。本次运行配置变更只将 GEO 独立环境文件中的 `DASHSCOPE_MODEL` 从 `deepseek-v4-flash` 改为已验证的 `deepseek-v4-flash-0731`。

- 在服务器本地保存受限权限备份，不复制密钥到工作区或输出。
- 原子更新独立环境文件，保留其他配置、文件属主和权限。
- 只重启 geo-service，复核健康接口及生效模型，再做一次带台账的 JSON 验证。
- 不修改共享环境、SEM/SEO 服务、BAIDU_WRITE_DRY_RUN、数据库结构或客户任务。
- 官网自动执行继续 reserved；本次连通性验证不能代替内容质量验收。
- 新模型单价需要与供应商分时/缓存规则匹配。当前没有匹配报价的调用继续显示待计价，不沿用旧别名单价。

## 稳定性开发

GEO 窗口负责来源 ID、可见正文、Schema/llms 代码装配及供应商错误分类；SEO 窗口负责 URL/缺项和冲突处理。各模块分别提交、测试和创建生产分支 PR，由总控审查、真实模型复测后发布。

## 执行验收

- 执行时间：2026-10-10 14:50:54 UTC（北京时间 22:50:54）。配置变更前的计划提交为 b5a6db99。
- GEO 独立配置已原子更新为 deepseek-v4-flash-0731；原配置受限备份保存在服务器本地。共享环境逐字节一致，SEO/SEM 进程未被重启。
- GEO 健康接口 HTTP 200、db=ok。重新读取运行进程环境确认新模型已生效，并用生效配置真实调用得到精确 JSON {"ok":true}。
- 本次只修复运行配置，应用发布代码仍为 d648b0c8a8df176c0b3b4fc08142b7b6dd670127。稳定性代码开发、质量评测与发布另行记录。

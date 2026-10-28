# SEM阶段0：输入、检查规则与内部模板

本目录是2026-10-28批准的阶段0交付。仅①新开户、③长期新品/限期活动；②换页返回未开放。
它提供可挂接的SEM API契约和本地持久化，不接入生产入口，不构成规划AI、影子流水线或客户批准。
一次性开发时间估算11～18h，不是日常运行耗时。后续1a需本阶段汇报后另开。

## P1入口和归属

`app.sem_phase0.router.create_router(store, resolve_principal)`返回FastAPI路由：

- `POST /api/v1/sem/phase0/submissions`：multipart，`metadata`为`LandingSubmission` JSON，`screenshots`为可选PNG/JPG/JPEG文件列表。
- `GET /api/v1/sem/phase0/submissions/{tenant}/{account}/{page}/{revision}`：返回该版本内容及截图hash/序号/尺寸。

每个POST只对应一页，所有图片自动绑定该页和本次版本。页面ID不可重绑产品线或URL，新页面用新ID；旧内容/附件不被覆盖。
`expected_revision=0`新建，后续必须等于当前版本；SQLite事务串行化同页竞争，过期提交409。
提交人、提交时间、版本及SHA-256由服务端记录，不接受客户端伪造提交人或批准状态。
提交始终为`blocked_draft`、`customer_confirmation=pending`、`execution_export_enabled=false`。
顾问不能代客户确认预算/品牌/结构；纯格式且投放内容不变的复核细则在后续批准流程实现。

`resolve_principal`是必需的**可信服务端依赖**，须从既有登录会话、顾问授权、SEM启用/暂停状态和账户所属tenant记录计算
`AdvisorPrincipal(actor_id, role='advisor', writable_accounts=frozenset({(tenant, account)}))`。
不能从客户端JSON、裸Header、查询参数或通用API key直接构造此权限。
工厂不提供默认身份/默认账户；服务层读写都会再查传入权限集合，客户角色和不匹配tenant/account均403。
本轮不挂载到`app.main`，避免扩大现有权限、改变授权失效处理或触发任何同步。
正式挂接时的既有鉴权适配与真实数据存储审核属于1a入口工作，不能把测试身份用于生产。

## 输入和截图

具体必填及类型以`contracts.py`为准：URL、长文本、产品线、页面ID、租户账户、情况、账户已就绪声明、目标、预算分/周期/币种、价帽、地域、时区/时段、品牌规则、显式否词列表、开始/结束、链接来源和内容授权范围。
预算无默认值，不接受浮点/字符串/布尔冒充整数分；货币当前只支持CNY，时区当前只支持Asia/Shanghai。
活动必须有截止；长期新品等无截止必须显式`no_deadline_explicit=true`；带截止不能同时选择无截止。
URL仅检查语法、HTTP(S)、端口、凭证和明显本地地址，不解析DNS、不访问URL，绝不视为已完成未来SSRF抓取防护或线上事实核验。

本地输入保护值采用PLAN V的建议上限，作为本轮合成自测契约值，不代表已批准真实客户数据接入：文本50000字符，每图10MiB、每页10张/30MiB、20百万像素/最长边10000。
检查扩展名/MIME/解码格式和静态单帧，拒绝文档及伪装；重新编码像素为PNG，去掉EXIF/GPS/ICC/注释，存原字节hash→清洗hash映射及清洗副本。
不保存原始文件名或原始字节，截图状态固定`not_connected`，不OCR。
Pillow是可选本地解码依赖，`requirements-sem-phase0.txt`锁定13.0.0；开发测试依赖引用它，不改CI配置。

`SubmissionStore(Path(...))`只创建显式指定的独立SQLite文件，不读应用配置、`.env`或生产库，不创建/迁移生产表。
路径须为操作者有权使用的私有本地目录。当前仅用于合成契约演练；实际附件ACL、隔离解码进程/超时、留存销毁、受控服务数据库适配在1a接真实输入前补齐。
无自动启动、无全局存储实例、无客户工作台入口、无TXT/DOCX/PDF、无真实抓取、无OCR/模型/百度业务调用。

## P6配置骨架

`rules.py`的`RULE_CATALOG`列出硬规则和未实现占位；`check_plan(CheckInput, RuleConfig)`是无外部副作用的纯函数。
预算采用整数分，单根、无重复/缺父/成环，同币种/周期；父预算=子合计+显式预留，差额0分。账户帽未知或超帽阻断。
字数上限和计数方式由配置显式提供，不把测试值说成百度限制；来源非空且须复核。
否词误伤、线上事实核验和冲突裁定只接受上游已完成状态；未知/失败阻断，不伪装已实现这些检查器。
`rules.internal.json`默认所有官方限制待核实，不能通过正式检查。
即使合成测试配置全部通过，执行出口仍固定关闭，顾问/客户批准流程没有实现。

## P10及验证

`TEMPLATE_NOTES.md`区分官方历史API证据和当前批量文件待核实项。
`synthetic.internal.json`标识“内部演练/不可上传百度”，字段以`internal_`命名，不是百度表头。
生成器仅输出内部JSON，拒绝CSV/XLSX扩展名；正式导出函数始终抛错。

本地测试（不需要.env、模型密钥、百度账号、网络或生产库）：

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q tests/test_sem_phase0.py
python -c "from pathlib import Path; from app.sem_phase0.templates import write_internal_sample; write_internal_sample(Path('docs/sem-phase0/synthetic.internal.json'))"
```

测试全部使用临时SQLite、虚构身份、example.invalid和本地合成图片。

# SEM阶段1a第一刀：合成影子规划骨架

**内部规划/演练，不可上传百度。** 本切片只覆盖①新开户和③新品/活动。依赖阶段0 Draft #818、基线23c39b4；未合并、未部署，也未挂到app.main。一次性开发时间估算12～20h；完整1a仍为85～135h开发时间，这些是估算，不是实际耗时。

## 本刀流程

1. P0/P1：在阶段0本地提交版本上创建演练规划，重新校验情况及账户已开好声明。仅内置101/201与102/202合成账户。权限仍由可信服务端注入AdvisorPrincipal，每个读写、导入、导出均查tenant/account与顾问角色。客户身份不能提交或导入。
2. P2：CaptureAdapter/OcrAdapter协议可供以后另批适配；当前只实现FixtureCapture/FixtureOcr。fixture_adapters默认fixture，所有其他后端名均拒绝，代码中无HTTP客户端、OCR SDK、模型接口或环境变量开关。假OCR文本是预写夹具，不执行识别，不读取真实截图。来源记录原文SHA-256、fixture/页面/阶段0版本定位。
3. P2a：按字段展示HTML、假OCR、提交文本候选及冲突。默认HTML识别值优先，其次假OCR，最后提交值。必须由顾问明确提交裁定；可按字段选择已存在的候选来源并填理由，记录操作者、时间及所选来源。两侧识别无结果时可降级提交字段，合计仍缺product/benefit/keywords则阻断并返回P1。
4. P3：从裁定来源以固定规则生成项目→方案→单元→词、基础创意、高级创意占位，以及显式否词、预算/地域/时段/价帽/品牌/目标/起止边界。每行source_refs；方案名、单元名、词及创意等推断保持pending_verification，Excel显示“待核实”。未接大模型，不外发输入。
5. P5/P6：与本批跨单元及当前合成账户现有资产查重，NFKC、空白归一、大小写归一后同类同文案重复硬阻断逐项批准。复用phase0 check_plan做预算、账户帽、字数、来源、否词误伤及冲突检查。内部字数保护值不是百度限制。官方限制未核实、线上事实未知、推断未核实一直阻断，P6不会因演练复核变为通过。
6. P7：导出内部XLSX→顾问修改内容/结构预算列→导入预览→显式应用预览→逐行提交顾问演练复核。预览不改规划；应用后规划版本递增、全部旧复核失效并重跑P5/P6。精确重复、预算树/帽、否词误伤、已知字数及声明预算不一致均阻断演练复核。未知官方规则与待核实状态始终展示，演练复核仅记录审阅，不授予放行资格。
7. P8/P8a：完成顾问逐项演练复核后可导出“客户审核表样例”，由顾问导入客户演练修改并看差异；只能预览，不应用、不记录客户批准，不实现回复凭证/正式确认链。
8. P13：传入合成时钟生成截止提醒建议，包含来源及due，无截止则无建议；不排程、不自动暂停。
9. P9及以后：无路由，export_execution/enable_plan始终抛PermissionError。状态固定mode=rehearsal、customer_confirmation=pending、execution_export_enabled=false、enable_allowed=false。

## Excel约束与版本

三页为“内部规划”“来源”“演练绑定”，第一页红色醒目标识禁止上传，内部列不冒充百度表头。只有内容及预算列允许修改，改后保留原来源且标待核实，差异和文件hash进审计。原始来源/裁定、行ID/父ID/类型/核实状态/复核列不能在Excel篡改，不能增删行或改变顺序。下一刀再扩结构编辑。

本刀仅一方案/一单元；分配预算须满足父子合计且不能覆盖P1声明预算。其他投放边界的编辑可留作待核实预览，但不会获得正式放行；应回P1创建新来源版本。服务操作发现阶段0同页更高版本立即409，旧规划必须重建。版本、plan_id、规划hash、来源hash、用途全部绑定；防跨规划、跨用途、重放。Excel复核列不能代替服务端逐项复核。

导入限2MiB、100 ZIP成员、解压10MiB、1100行/8列；拒绝公式、超链接、外部关系、实体声明、宏、目录穿越及异常ZIP。导出对以=开头的来源强制文本。非本模块Excel不能作为导入输入。只提供内部XLSX，不提供任何百度正式CSV/TXT/XLSX。

## 本地调用与验证

依赖：requirements-sem-phase0.txt及requirements-sem-phase1a.txt；开发测试依赖已引用，不改CI。

```powershell
python -m pytest -q tests/test_sem_phase0.py tests/test_sem_phase1a.py
python -m app.sem_phase1a.demo --output docs/sem-phase1a/samples
```

demo只加载本地合成fixture、在系统TEMP创建/销毁独立SQLite，输出合成冲突、全规划、查重阻断、顾问Excel改前/改后及差异、客户演练表及差异、到期建议。不会启动服务、抓页、OCR、调用模型或业务接口。样例包含随机演练ID与审计时间，不视为真实客户凭证。

create_router(ShadowService(submission_store), resolve_principal)提供可挂接API，前缀/api/v1/sem/phase1a/shadow。POST /plans绑定阶段0页版本；GET /plans/{id}读状态；POST rulings裁定并生成；GET excel/{advisor|customer}导出；POST previews/{audience}以file上传；POST apply-preview显式应用顾问预览；POST approvals逐项演练复核；GET expiry-suggestions读取建议。请求模型见contracts.py，API合成全流程见tests/test_sem_phase1a.py。

## 隔离和下一刀

SubmissionStore是显式TEMP/私有路径的阶段0演练SQLite，规划服务仅进程内存、RLock保护同进程版本变更，重启不保留；返回值深拷贝，历史版本/裁定/审计hash链可导出复核。**不是生产持久化、不可据此接真实账户或真实输入。** 跨进程并发事务、服务存储/附件ACL、真实会话授权适配、配额/超时/留存、HTML通用解析、OCR区域置信度及复核、复杂结构编辑都未做。

下一刀先另定持久化与版本事务边界、现有鉴权适配（不扩大sem_runtime），继续本地合成影子证据，再处理多方案/单元及结构编辑。真实HTTP/OCR/模型须单独获准，不能直接解除fixture硬限制。情况②、正式客户确认和凭证、百度模板与执行继续关闭。合成测试不替代PLAN规定的影子天数/账户/样本门槛。

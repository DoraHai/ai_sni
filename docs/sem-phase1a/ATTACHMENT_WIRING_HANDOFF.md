# SEM 私有附件生产接线 Draft

本分支独立基于 slice6 cda2b401，不依赖迁移重编号 PR。仅准备发布包代码，不开桶、不写 RAM/DB 授权、不改 101 .env、不部署。

生产 `routers()` 装配读取以下五个环境变量，均去除首尾空白，齐全才创建 oss2 AuthV4/Bucket 并注入 OSSPrivateAttachmentStore：

- SEM_ATTACHMENT_OSS_BUCKET
- SEM_ATTACHMENT_OSS_ENDPOINT
- SEM_ATTACHMENT_OSS_REGION
- SEM_ATTACHMENT_OSS_ACCESS_KEY_ID
- SEM_ATTACHMENT_OSS_ACCESS_KEY_SECRET

缺任一、空白、SDK 导入或任一构造异常均返回 attachments=None，应用可继续启动；含附件的来源提交返回 503 / ATTACHMENT_STORAGE_UNAVAILABLE，纯文字来源仍按原契约工作。构造只创建本地客户端，不探测或创建桶；未配置桶时保持原失败关闭行为。没有 ENABLED 开关、默认凭据或磁盘回退。

对象键仍为 sem-sources/，适配器原私有 ACL、AES256、不可覆盖写、hash 回读、有限重试不变。SDK连接/读取 timeout=(3,10) 秒，复用原常量；socket timeout 不等于绝对 deadline，既有单对象20秒检查/批次60秒与请求90秒装配要求仍按 slice6 交接另审，本 Draft 不宣称已完成绝对期限治理。

应用不记录配置值或SDK异常。oss2 DEBUG诊断可包含配置和签名头，装配禁用已加载 oss2.* 日志与 urllib3.connectionpool 诊断，后者是共享HTTP连接日志，会同时停止其他使用该logger的连接诊断；业务日志不变。异常不会携带凭据向上冒泡。

仓库Python依赖采用固定requirements，无既有Python lockfile。requirements.txt引入requirements-sem-attachments.txt的12项固定SDK依赖，已有共享cryptography保持原版本；无前端依赖或lock变化。新增12项逐版本调用官方OSV querybatch，零已知漏洞；现有CI OSV前端lockfile检查仍须绿色，不将其说成Python全依赖审计。

离线测试28项覆盖齐备注入、五变量分别缺失/空白、import/Auth/Bucket/适配器构造失败、真实SDK仅本地构造、真实生产routers+SQL仓库+OSS stub附件201及缺项/失败503、日志及响应不含配置。slice5/6回归合计543 passed / 2 skipped（本机无隔离PG，以CI为准）。未使用真实密钥或云端附件连接。

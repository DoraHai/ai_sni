# GEO 与共享静态三文件的发布兼容矩阵

本轮采用已协调的B方案：GEO发布后端+Vue；SEM负责人从其已审生产基线，以其受控整包流程配套交付三个GEO静态文件。不实施新打包/manifest/nginx方案，不从GEO旧树重建SEM，不手改已发布目录。

## 版本与证据

- H0/J0：实际线上a22263c08461静态HTML/JS。git show三文件SHA256与/opt/sem-frontend/current中三文件完全一致，不是仅凭目录名推断。
- H1：d1a4f99的editor/channels（本次未改HTML）。J1：本次追加缺revision前置拒绝后的geo-api-v1.js，区别于未加此保护的d1a4f99 JS。
- B0：线上611d331后端；GET export会登记状态并commit。
- B1：已审d1a4f99后端；GET export纯只读，POST才登记。本次只改静态JS/测试/本文，后端没有新差异。
- J0的exportVariant为两参数调用，api默认GET。H0复制后还调用getTask，再renderAll/loadDetail。实际源码与VM复现存于本地GEO_STATIC_COMPATIBILITY_d1a4f99.json（它记录加前置保护之前的危险混版，不能当成当前结果）。

## 复制按钮矩阵

本表只描述点击复制链路，不宣称整张旧页面加载过程只读。视图读取仍需满足菜单、客户归属及新入口GEO资格。

|HTML/JS|旧后端B0|新后端B1|
|---|---|---|
|H0/J0|旧export GET写状态；之后getTask也可能初始化配置。旧行为，不是只读|export GET已纯读；但后续getTask仍可能初始化渠道。仅功能兼容，过渡期间不算全链只读|
|H0/J1|旧两参数调用缺revision，JS在api前拒绝并提示刷新，网络0次|同左，网络0次，既不POST也不回退GET/自动补revision|
|H1/J0|旧JS没有previewVariantExport，客户端失败，复制调用不发请求；必须硬刷新HTML/JS|同左；错误由现有showError显示，不能静默回退旧函数。现场提示用户硬刷新|
|H1/J1|会调用旧export GET，旧后端仍可能写状态。**禁止先发新静态或在回滚后继续宣称复制只读**|只GET取保存内容并复制，不登记、不getTask、不刷新任务状态，view用户可使用|

H1编辑器对未保存修改在请求前提示保存；请求期间编辑/切客户/切页签/服务端正文改变则停止复制。母稿直接复制当前输入，提示未执行保存。显式登记的有效小写64hex revision仍发一次POST：B1依权限/资格/版本校验执行；B0无POST入口不会自动回退。旧HTML两参调用从未携带revision，J1必须在网络之前拦截。

## 可执行发布顺序（由工作台负责人统一放行）

1. 冻结GEO新候选和SEM三文件候选，明确各自生产基线、整包验证和回滚产物；SEM产物其余文件差异由SEM负责人核验。本次不单独发布测试/文档。
2. GEO后端+Vue先按原受控流程配套发布。先核对前后端实际SHA、健康/TLS、GET export/readiness只读冒烟和记录摘要；不做POST登记、采集、生成或文章发布。
3. 在SEM静态包完成前，暂停旧静态复制链路的业务验收，不宣称全链只读。H0/J0搭配B1功能可过渡，但getTask残余副作用仍存在；不能把“后端GET改好了”当两套前端已交付。
4. 由SEM负责人用已审产物受控切换三文件所在门户包。核对实际公共URL与产物的三个SHA256、路由仍归原门户、非目标SEM文件未变。GEO不写SEM目录、不改Nginx。
5. 两包就位后通知旧页面强制刷新；确认实际加载H1/J1而非仅看页面标题。正常复制只GET，混版应明确失败；不得因为错误自动调用旧export或GET重试补版本。仍保留共享JWT真实身份联调未完成的边界。

## 回滚边界与顺序

- 若GEO在SEM发布前失败，按GEO原流程回611d331；共享门户保持原版本。恢复的是旧功能，其GET仍会写状态，不能标“只读修复完成”。
- 若两包发布后需回B0，先暂停静态复制/相关验收，协调SEM恢复旧三文件产物，再回GEO后端+Vue到611d331并检查两边实际版本。不能留H1/J1配B0继续操作。
- 浏览器缓存不随服务器回滚自动清理；新HTML/JS仍可能驻留并调用B0 GET。因此回滚期间与回滚后必须明确该修复已撤回、停止按只读流程验收，提示刷新。仅靠前端revision guard不能防止新copy GET在旧后端写入；若要求技术上禁止访问整个回滚窗口，需要服务器负责人另行批准的访问控制，不属于本包已实现能力。
- 不强推退生产分支，不改历史任务/文章来补验收，不把混版失败误报成功。若SEM不能在计划窗口配套完成，先停在已确认状态并回报负责人，不能擅自补拷文件。

## 最终静态三文件（同一候选取值）

|路径（frontend/public/deal-sniper-prototype/geo下）|SHA256|
|---|---|
|editor.html|143a3f2628cd3e76f9e9ce7c8b64cf97fd0c0b924aa22a090e25912b35f5bd9a|
|channels.html|5aff894d96a6ca086fe40f9a9163435da565ffbe58ebdf1ce997ba5d3f7dd8f9|
|assets/geo-api-v1.js|1b58fbb1f33370d67fa75000ee817519b506c3615d11481a76271e6eab8ef3ff|

验证：静态复制专项10 passed，含实际旧HTML两参调用契约+新JS网络0次、非法revision不回退、有效revision只POST。前端全量157 passed、无跳过，GEO构建通过。本次后端未改，不重复本地全量；真实PG/后端证据为此前结果，远程新候选CI另行登记。

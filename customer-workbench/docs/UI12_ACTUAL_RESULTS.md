# UI-12 实际联调与体验记录

2026-10-08，北京时间。结论：真实账号、稿件修改审核、两种确认及版本冲突已走通；当前connected页面仍是接口接线层，未完成面向客户的产品体验。不能用原r12演示的完成度，或脚本的passed字样，代表完整工作台已交付。

## 实际执行结果

浏览器使用当前四文件编译产物，初始前端 `d49790445e7edeaa1873136bcf44f49047cc3138`；后端初始 `56bb95d78edd6937d3f24f1897ddf57cabdc057f`，`127.0.0.1:8031`。健康检查200、DB/schema正常、revision为0105。配置文件SHA256为 `10d6efa53eccdf01708d0b97f35188f71c1385f533aa36fb7d28226057ff30cb`，不保存其密码内容。

后段后端修复为 `f97be7800a934c0d19954270e467b79c6318b324`，更新配置SHA256为 `34983b88b70b52b770d72204b5205bdd66cd25eb3df69475a6092999bbdbaff6`；前端误标修复后的产物为下述d713962f。最终证据提交只继续归档脚本/文档，产物内容与d713962f一致。

| 场景 | 结果与可核对事实 |
| --- | --- |
| 顾问/客户登录及首页、计划、进度、数据 | 已通过。真实密码校验/JWT及PG角色；原session.setAuth与编译入口bootstrap。目录modules/tenants使用SEO明确提供的本机真实PG桥，不能当共享登录网关部署验收。 |
| 顾问轻改→提审→审核→客户确认 | 已通过。content1由v1改为v2；客户actor1确认v2及实际hash。客户编辑、代确认按钮禁用。 |
| 顾问代确认 | 已通过。content2 v2，advisor actor2，actor_mode=advisor_proxy。 |
| 旧版本人工登记冲突 | 已通过。顾问保留v2登记表；客户合法退回，另一顾问页改至v3；旧表POST返回409 content_version_conflict。读回发布ID不变，未自动重发。 |
| 正常人工登记 | 初次500，停止后经SEO确认未落库并修复后端，再读ready/approved及空发布列表，从断点只提交一次，最终200。publicationId=1、content2/sourceVersion2，not_queued/capture_disabled。 |
| 任务进度与接续 | 初次读task1为in_progress/awaiting_confirmation；登记后通过页面选中发布记录1，只接续一次。最终in_progress/page_evidence_needs_attention、blocker=capture_disabled、completionEvidence=null，未伪造完成。 |
| 顾问撤权 | 已通过。SEO撤销分配后，真实content3仍ready而assignment=false、代确认/编辑/登记均禁用；UI只登录/GET。SEO随后恢复为active=true，后段登记验证了恢复后的操作可用。未测在途撤权竞争。 |
| 计划保存、四类新任务触发、AI生成、网站诊断、冻结月报 | 本轮未执行。计划等页面只读；task1由SEO此前真实API准备，不能计作本UI创建成功。 |
| 公网页面、真实AI、渠道发布 | 未执行。外部操作与调度关闭；人工登记输入只是合成事实，页面证据未生成。 |

初次workflow在500停止，后续只读观察没有重放前段业务。UI没有直连数据库或替换身份，数据库生命周期和后端修复由SEO负责。

SEO报告500涉及带时区时间写入无时区PG列，以及回填提交后读取未刷新的更新时间。由SEO修复并重启服务；本UI只核验其中实际人工新建登记从500变为200，已有记录complete回填的修复未在本轮浏览器覆盖。业务写入已结束，顾问分配已恢复；环境释放由总控和SEO安排，UI未清库。

## 三个最实际的体验发现

1. **会丢掉用户刚输入的内容，尚未修。** 顾问在计划备注和稿件正文输入但不保存，切到进度再返回，输入都恢复为服务端旧值，没有离开提示（dialogs=0）。这是实际可用性缺陷；观察脚本成功只表示复现完成。错误后登记表与输入也会被清空，实际500页面只有“结果未知，请重新读取核对”。以后修保留草稿需限制在同身份、同客户、同站点内，撤权/退出/切客户仍应清理。
2. **客户能确认，但阅读和理解费力。** 实际正文直接显示`<p>`标签；页面外露hash、actor编号、英文状态和完整ISO时间。客户还会看到大量属于顾问的禁用轻改/复核/登记按钮；计划是一整页禁用表单，并提示缺少编辑权限，而不是客户可理解的业务摘要。数据L2为原始JSON，L3重复接口地址；这不能算面向客户的数据解释。
3. **版本保护确实有效，但产品路径没有做完整。** 旧版本登记被真实409拦住，页面有重读入口且不重发，这是顺畅点。相对地，首页与内容基本为同一稿件列表，SEO工作与数据复用准备状态；空消息栏一直占据桌面宽度，移动端排到正文后面形成长页。交付记录只围绕本次读过的稿件，不能当完整历史。390像素无横向溢出，只能证明未溢出，不能证明操作轻松。

以上前三项均来自实际页面和操作。关于客户是否容易理解、路径是否需要重做是基于这些观察的产品判断，没有做真实客户访谈。

## 本轮已修的语义错误

实际content1退回并改到v3后，历史v2记录原来仍显示绿色“客户本人确认”。本地提交 `d713962fbd8d1b05ede2c39926002f6d6e2d5806` 改为按decision显示确认/退回，旧记录明确“对应旧版本，当前版本尚未确认”，只有当前approve保留绿色；历史记录保留。

13项相关客户端检查通过；重建后真实浏览器只读核验content1 v3/latest reject v2通过，桌面与窄屏均已截图。没有再次改稿或确认。其他布局和输入丢失问题本轮未修改。

## 截图和原始报告

以下目录均为本机TEMP，不含登录截图、密码或令牌。JSON只记录角色/对象/版本、接口路径/状态与外部边界。

- 预检：[report.json](C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui12-preflight-BNmRYR/report.json)。
- 初次业务链及500：[report.json](C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui12-scenarios-eYVlOw/report.json)；同目录 `customer-confirmed.png`、`manual-form-exact-version.png`、`manual-version-conflict.png`、`failure-page-1.png`。
- 页面全景：[report.json](C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui12-scenarios-GAR2ov/report.json)。同目录含两角色各自的 `advisor/customer-home.png`、`-content-list.png`、`-plan.png`、`-progress-list.png`、`-data.png`、`-current-content.png`；另有 `advisor-task-1.png`、`advisor-publication-readback.png`、`customer-content-mobile.png`。
- L1/L2/L3与未保存输入：[report.json](C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui12-scenarios-I2sc4l/report.json)。同目录 `advisor-data-L1.png`、`advisor-data-L2.png`、`advisor-data-L3.png`、`plan-unsaved-before-navigation.png`、`plan-after-navigation.png`、`draft-unsaved-before-navigation.png`、`draft-after-navigation.png`。
- 误标修复：[report.json](C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui12-scenarios-QTP2IK/report.json)；[桌面截图](C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui12-scenarios-QTP2IK/customer-historical-rejection-corrected.png)与同名 `-mobile.png`。
- 撤权：[report.json](C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui12-scenarios-ibkVHy/report.json)与同目录 `revoked-advisor.png`。
- 后端修复后的断点接续：[report.json](C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui12-scenarios-3xK0Hj/report.json)；[登记结果](C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui12-scenarios-3xK0Hj/manual-registration-success-after-backend-fix.png)、[任务证据阻塞](C:/Users/ADMINI~1/AppData/Local/Temp/workbench-ui12-scenarios-3xK0Hj/task-1-awaiting-page-evidence.png)。最后一个文件名概括等待证据，准确服务端phase为page_evidence_needs_attention。

桌面视口1440×1000，窄屏390×844，截图为整页。尚未推送、合并或部署本轮提交。

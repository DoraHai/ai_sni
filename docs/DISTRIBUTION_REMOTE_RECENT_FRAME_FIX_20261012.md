# 远程画面持续刷新竞争修复

总控真实顾问网页与多号通GUI联调发现：执行端每750ms上传画面，顾问每1s读取；顾问已看到A，后台B先上传，旧实现要求输入引用最新上传seq，正常点击会随机409。本次修复只改变中央对已提供画面的有效期判断，wire字段、SQL、原生审批和SEM不变。

代码冻结：`d6f4747db5cf576dc9ac79f4e7214c4cc3bdd0e4`，tree `130cf1cb81b3fcc845a7bebdb9521c51417f98ed`。在前次e82文档提交之后cherry-pick这一个代码提交即可；本报告后续提交仅docs。

服务器在当前顾问GET frame鉴权、数据库commit成功后，登记实际返回的seq、视口revision和原captured_at。每会话最多16条元数据，不保存第二份PNG。输入仅认可其中仍在5秒内、当前revision的画面。输入被接受后，其原capture时间作为私有内存依据随待处理命令保存，poll再核当前权限、revision及原capture期限；后来上传的新帧、读取更多帧导致历史容量淘汰，都不会单独把已接受命令误判unknown。该私有时间字段不进入设备响应、数据库或审计。

未读画面、错误顾问GET、GET commit失败、超5秒和旧revision均拒绝。视口变化、关闭、撤权、过期、owner丢失和重启清历史。单次poll、UUID去重、有限输入、当前source/task/lease、nonce、账号窗口及正式发布关闭保持原约束。不会自动重发失败输入。

本窗口自有PG55537、HTTPS55871实际验证19项通过，其中6项新增、13项受影响旧用例复核：

- A已读、B上传后用A输入成功；C再上传后poll仍只交付一次，ACK正常，设备响应字段未增加。
- 从未读、错误顾问读、失败GET commit不能授权输入；当前顾问成功读后可输入。
- 新B不能延长旧A的capture期限，input和delivery分别核5秒过期；delivery到期成为unknown。
- 17次成功读取后只留16条、最新PNG仅1份；已接受的第2帧命令即使随后被容量淘汰，仍按原期限交付。
- 复核7个PNG响应头、身份/范围、有限输入、重复命令、变视口/旧ACK、原生指派/角色撤销、绑定撤销、关闭、重启与owner丢失后的清理。

首轮19项有18通过、1失败：过期待交付命令已正确unknown，但过期已读元数据等下一次周期清理才删除。已补poll及时清理，冻结代码下同19项全通过。首轮XML保留，不覆盖首次总控真实409证据。没有重新跑与此改动无关的原生任务审批/容量等套件。

最终actual HTTPS health的6个文件SHA与冻结代码一致，PG无active remote session。JSON证据见 [DISTRIBUTION_REMOTE_RECENT_FRAME_EVIDENCE_20261012.json](DISTRIBUTION_REMOTE_RECENT_FRAME_EVIDENCE_20261012.json)。前轮公开证据原字节归档到私有TEMP的 `baseline-7a03c832`，本轮使用新XML/health/readback文件名；旧报告为历史checkpoint。

消费者仍为合成PNG执行端；真实顾问网页及多号通GUI由总控按新冻结版本继续复验，本报告不替代真实微信登录、验证码或发布网络拦截验收。没有生产或其他测试环境操作。

本窗口自有55537/55871/55872已停止并核无监听，数据与证据保留；未停止总控pilot或旧验收环境。

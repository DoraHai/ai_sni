# GEO 待办负责人和截止日期

工作台执行待办新增负责人姓名、截止日期的查看、修改及清空。负责人是手动姓名登记，不绑定用户权限或自动通知。可不填写；旧工单保持空值。

数据存储：GeoActionTicket 增加 nullable owner_name（100 字符）和 due_date（Date）。创建、更新接口支持这两个字段，接口响应返回姓名和 ISO 日期。姓名去除首尾空白，空白转为 null；省略字段时不覆盖已有值。后端校验日期是否合法和姓名长度。

逾期规则：按 Asia/Shanghai 日历日判断，截止日当天不逾期，次日开始逾期；已验收不计入。页面显示逾期计数及单项标签，每分钟更新当天日期。清空期限后不再计为逾期。

迁移文件：migrations/versions/20260905_0074_geo_ticket_assignment.py，前置 0073_geo_schema_repair，只给 geo_action_tickets 增加两个可空字段。升级保留旧数据；降级仅删除新增字段及其中信息。迁移链读取检查确认唯一 head 为 0074_geo_ticket_assignment。

部署前必须先在目标数据库完成该迁移，再启用读取新字段的后端。本轮仅写入迁移文件，没有连接或变更任何实际业务数据库；未提交、未推送、未部署。

验证结果：后端 514 项、前端 22 项通过；GEO 构建及 diff 检查通过。测试覆盖字段保存/省略保留/清空、非法日期/过长姓名、上海跨日/当天不逾期/已完成排除。迁移在临时 SQLite 内存数据库执行升级和降级，确认既有记录保留；这不等于 PostgreSQL 实库验证。日志 geo-ticket-assignment-tests.txt、geo-ticket-assignment-node.txt、geo-ticket-assignment-build.txt。

本地浏览器使用实际 Vue 页面和内存接口：填写负责人及过期日期、保存后读取、逾期计数为 1、清空期限后逾期计数归零且负责人保留均通过。控制台没有 error/warn。构建仍有既有大包提示。

# 共用链收编 GEO 每日检测 schema（待审核，不自动执行）

生产共用链由 production-seo 持有，新增 `20261023_0111_geo_autopatrol.py`：`0110_distribution_inbox -> 0111_geo_autopatrol`，一个head、完整父版本。SEO只识别新增schema版本，不开启GEO功能，不改变任何客户状态。

GEO本地链保留 `0074_geo_ticket_assignment -> 0075_geo_autopatrol`，其等价upgrade DDL只用于独立CI。不要把0111塞进GEO图，也不要把0075用于共用生产库。GEO ORM现有字段与两份DDL一致；两个分支迁移测试共同冻结同一DDL SHA256。

0095允许已核实的完整一致既有状态；0111没有已应用0075的证据，因此要求所有新增对象不存在，遇到部分/完整既有对象均失败。不使用IF NOT EXISTS跳过漂移，不自动stamp/回填/授权。支持正常0110增量升级及离线输出；不执行降级，应用回滚保留审计/日占位。

离线生产包在 [migration-0111/SUMMARY.md](migration-0111/SUMMARY.md)，与调度目录release/migration-0111逐文件一致。只允许另行人工审核执行；本PR和CI不执行生产迁移，部署workflow不变。权限由既有默认权限决定，apply在提交前逐项核验，不满足则回滚，不附加权限变更。

测试：完整共用图、冻结DDL、原GEO图及ORM；CI隔离PostgreSQL中原有数据/默认值保留、唯一日占位、审计序列、已有字段/表/索引/序列/全套结构全部拒绝、失败版本不前进、成功再次upgrade不重复执行。SEO旧迁移测试继续覆盖从旧分支合流到新head；SEO启动兼容集合及只读schema检查加入0111。

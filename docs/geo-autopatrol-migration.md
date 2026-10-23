# 顾问每日自动检测：迁移说明（待审核，不自动执行）

本 PR 只增加兼容 schema；不启用任何客户，不执行迁移，不含 GRANT，不放宽 sem_runtime。
实际运行角色和默认授权未知；上线前由获授权人员核对，权限不足时停止上线，不借用其他角色。

生产共用迁移链由 production-seo 管理：`0110_distribution_inbox -> 0111_geo_autopatrol`，
文件 `20261023_0111_geo_autopatrol.py`。生产只能使用共用链及单独审核的 0111 SQL 包，不能执行 GEO 的 0075。
GEO 本地链保留 `0074_geo_ticket_assignment -> 0075_geo_autopatrol`，只供独立 CI/夹具升级；不把 0111 文件直接搬到 GEO，避免缺失 0110 父版本或双 head。
0075 的 upgrade schema 与共用链 0111 完全相同；0111 额外要求所有新增对象均不存在，遇到已存在/部分存在直接失败，禁止自动收编未审核结构。
这沿用 0095 的双链收编模式，但生产尚无已执行 0075 的审核证据，因此不提供“已存在即接纳”路径。
settings 新增自助模式、负责人/授权代次/范围、开关与管理锁、开启和最后变更信息、版本、阻塞原因、每天手动次数（默认10）及其独立版本。
runs 新增可空 DATE auto_day、last_progress_at；部分唯一索引 `(tenant_id, auto_day) WHERE auto_day IS NOT NULL` 防每日重复。
新增 events 审计表（按 action 区分开关与手动额度修改，共用一套事务审计）及北京日 daily_budget 请求尝试账本。
旧客户默认 legacy、自助关闭；旧轮次 auto_day 为空。upgrade 只增不删，不改变旧列类型，不猜测回填历史。

发布前应由获授权人员对相关表做 pg_dump 备份（settings、runs 及现有相关 GEO 表），并保存 schema-only 备份、迁移版本和备份校验结果；备份位置及真实连接参数由授权流程提供，本文不包含。
仅在审核后由独立迁移流程升级到指定 revision。应用部署不夹带 upgrade/stamp/downgrade。
回滚应用时保留所有新表、列、索引及日占位，不执行 downgrade。
切入自助后必须保留识别 daily_self_service 的后端作为最低安全回退版本，避免旧版重新打开旧定时。

验证：本地运行静态图/DDL/ORM一致性测试；CI 的独立 PostgreSQL 临时 schema 验证空 schema 升级及有旧数据增量升级，销毁只限测试自己创建的随机 schema。
测试仅使用合成数据和 CI 的 loopback geo_ci 数据库，不连接业务数据库。

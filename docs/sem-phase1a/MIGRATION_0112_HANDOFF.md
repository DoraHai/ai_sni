# SEM 迁移重编号 Draft

| 旧 SEM revision | 当前 revision | down_revision |
| --- | --- | --- |
| 0077_sem_phase1a_shadow | 0112_sem_phase1a_shadow | 0111_geo_autopatrol |
| 0078_sem_phase1a_grants | 0113_sem_phase1a_grants | 0112_sem_phase1a_shadow |
| 0079_sem_phase0_sources | 0114_sem_phase0_sources | 0113_sem_phase1a_grants |

生产基线按 task17 为 0111_geo_autopatrol；本次没有连接生产库或执行 upgrade。
SEO 已使用 0077/0078/0079，同号异义。为让 Alembic 解析 0111 的完整祖先，从 production-seo 76ec9a14 原样导入 36 份缺失脚本（SEO 0075 与 0077–0111）；它们只是已上线脚本的只读副本，未修改逻辑。SEM 三步仅改文件名和 revision/down_revision，升级逻辑不变，只加不删，downgrade 仍拒绝。

建议由合并 #818–#824 与本 PR 后的 **SEM 后端发布包**，在 101 上以 sem_app 执行 alembic upgrade。本 PR 未合并前禁止 upgrade；不要从缺少 0111 的旧 SEM 包强跑。执行迁移仍需正式上线流程另行授权，本 Draft 不执行。

当前唯一 head 为 0114_sem_phase0_sources；从 0111 的升级计划恰好只有 0112→0113→0114，不重跑 SEO 历史。旧 GEO-head 的隔离 PostgreSQL 测试继续只升至其原测试目标 0074_merge_geo_seo_heads；完整解析与 SEM 新三步由独立测试覆盖。历史交接的阶段计数描述不代表当前迁移链。

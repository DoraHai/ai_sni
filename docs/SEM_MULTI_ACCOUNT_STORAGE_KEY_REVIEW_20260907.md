# SEM 多账户存储键只读诊断与候选设计（2026-09-07）

## 结论与范围

本文件只记录代码和数据库元数据的只读诊断方案，不修改模型、不生成或执行迁移、不读取生产客户数据，也不触发百度同步或投放。

当前 SEM cockpit 查询已经按 `tenant_id` 和 `baidu_account_id` 隔离读取，并把 `baidu_account_id IS NULL` 的历史记录保留为独立未归属桶。不过，以下四张关键词相关表的唯一键和同步 upsert 冲突键没有包含 `baidu_account_id`。如果同一租户下不同百度账户出现相同外部 `keyword_id`，后同步账户的行会命中先同步账户的键并更新 `baidu_account_id` 与指标。只读层无法恢复此前被覆盖的记录，只能以 `completeness=unknown` 返回当前已存证据。

代码库没有百度 `keyword_id` 跨账户全局唯一的契约或校验。百度请求使用单个账户的授权上下文，模型又把 `baidu_account_id` 作为来源维度，因此不能仅凭现有代码排除跨账户碰撞。是否在真实数据中发生过碰撞，必须由数据库负责人运行下方只读检测并结合百度侧账户资料确认。

## 受影响的键

| 表 | 当前唯一键 / 约束名 | 当前同步 upsert 冲突键 | 风险 |
| --- | --- | --- | --- |
| `keywords` | `(tenant_id, keyword_id)` / `uq_keywords_tenant_kw` | `(tenant_id, keyword_id)` | 两账户同 `keyword_id` 只能保留一行，账户归属和资产字段可被后一次同步覆盖 |
| `kw_report_snapshots` | `(tenant_id, report_date, keyword_id, device)` / `uq_kw_report_tenant_date_kw_device` | 同左 | 两账户同日、同词、同设备的指标不能并存，后同步行会替换账户归属和指标 |
| `keyword_region_reports` | `(tenant_id, report_date, keyword_id, region_name, region_level, device)` / `uq_kw_region_report_tenant_date_kw_region_device` | 同左 | 不同账户同地域维度的行不能并存 |
| `keyword_hourly_reports` | `(tenant_id, report_datetime, keyword_id, device)` / `uq_kw_hourly_report_tenant_dt_kw_device` | 同左 | 不同账户同小时维度的行不能并存 |

相邻的 `campaigns`、`adgroups`、`price_strategies`、`ocpc_packages` 和 `kw_region_snapshots` 也采用未包含账户 ID 的租户级外部键。正式 schema 评审应决定是否一次统一治理；本文件的最低修复范围只覆盖 cockpit B 直接读取的四张关键词表。

`search_term_reports` 不使用这些 upsert 约束。其同步按租户和账户替换窗口快照，cockpit 返回每个账户的独立窗口，因此不属于本次唯一键候选。

## 只读检测 SQL

以下 SQL 只读取元数据和现有行。运行前应连接只读副本或使用只读事务，并保存查询时间、数据库版本与结果行数。不得在本诊断中执行 `ALTER`、`UPDATE`、`DELETE`、同步或补采集。

### 1. 确认实际约束定义

```sql
BEGIN READ ONLY;

SELECT
  conrelid::regclass AS table_name,
  conname,
  pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE contype = 'u'
  AND conrelid IN (
    'keywords'::regclass,
    'kw_report_snapshots'::regclass,
    'keyword_region_reports'::regclass,
    'keyword_hourly_reports'::regclass
  )
ORDER BY conrelid::regclass::text, conname;

ROLLBACK;
```

### 2. 找出多账户租户与未归属行

```sql
BEGIN READ ONLY;

WITH multi_account_tenants AS (
  SELECT tenant_id, count(*) AS account_count
  FROM baidu_accounts
  GROUP BY tenant_id
  HAVING count(*) > 1
)
SELECT
  m.tenant_id,
  m.account_count,
  (SELECT count(*) FROM keywords k
    WHERE k.tenant_id = m.tenant_id AND k.baidu_account_id IS NULL) AS keyword_unassigned,
  (SELECT count(*) FROM kw_report_snapshots r
    WHERE r.tenant_id = m.tenant_id AND r.baidu_account_id IS NULL) AS report_unassigned,
  (SELECT count(*) FROM keyword_region_reports r
    WHERE r.tenant_id = m.tenant_id AND r.baidu_account_id IS NULL) AS region_unassigned,
  (SELECT count(*) FROM keyword_hourly_reports r
    WHERE r.tenant_id = m.tenant_id AND r.baidu_account_id IS NULL) AS hourly_unassigned
FROM multi_account_tenants m
ORDER BY m.tenant_id;

ROLLBACK;
```

### 3. 检查同一关键词在不同表中的账户归属漂移

当前唯一键会阻止同一表内同时保留碰撞行，所以不能通过单表 `GROUP BY` 证明历史覆盖。下面的跨表检查可以发现同一租户、同一 `keyword_id` 在资产、日报、地域和小时证据中指向不同非空账户的现状；结果是需要人工核对的强信号，但空结果不能证明从未发生覆盖。

```sql
BEGIN READ ONLY;

WITH provenance AS (
  SELECT tenant_id, keyword_id, baidu_account_id, 'keywords' AS source
  FROM keywords
  UNION ALL
  SELECT tenant_id, keyword_id, baidu_account_id, 'kw_report_snapshots'
  FROM kw_report_snapshots
  UNION ALL
  SELECT tenant_id, keyword_id, baidu_account_id, 'keyword_region_reports'
  FROM keyword_region_reports
  UNION ALL
  SELECT tenant_id, keyword_id, baidu_account_id, 'keyword_hourly_reports'
  FROM keyword_hourly_reports
), conflicts AS (
  SELECT
    tenant_id,
    keyword_id,
    count(DISTINCT baidu_account_id) FILTER (WHERE baidu_account_id IS NOT NULL) AS account_count,
    array_agg(DISTINCT baidu_account_id) FILTER (WHERE baidu_account_id IS NOT NULL) AS account_ids,
    array_agg(DISTINCT source ORDER BY source) AS sources,
    count(*) FILTER (WHERE baidu_account_id IS NULL) AS unassigned_rows
  FROM provenance
  WHERE keyword_id IS NOT NULL
  GROUP BY tenant_id, keyword_id
)
SELECT *
FROM conflicts
WHERE account_count > 1 OR unassigned_rows > 0
ORDER BY tenant_id, keyword_id;

ROLLBACK;
```

### 4. 检查账户覆盖和最近更新时间

```sql
BEGIN READ ONLY;

WITH keyword_counts AS (
  SELECT tenant_id, baidu_account_id, count(*) AS row_count, max(synced_at) AS updated_at
  FROM keywords
  GROUP BY tenant_id, baidu_account_id
), report_counts AS (
  SELECT tenant_id, baidu_account_id, count(*) AS row_count, max(fetched_at) AS updated_at
  FROM kw_report_snapshots
  GROUP BY tenant_id, baidu_account_id
)
SELECT
  a.tenant_id,
  a.id AS baidu_account_id,
  a.status,
  coalesce(k.row_count, 0) AS keyword_rows,
  coalesce(s.row_count, 0) AS report_rows,
  k.updated_at AS keyword_updated_at,
  s.updated_at AS report_updated_at
FROM baidu_accounts a
LEFT JOIN keyword_counts k
  ON k.tenant_id = a.tenant_id AND k.baidu_account_id = a.id
LEFT JOIN report_counts s
  ON s.tenant_id = a.tenant_id AND s.baidu_account_id = a.id
ORDER BY a.tenant_id, a.id;

ROLLBACK;
```

多账户租户中，已同步账户长期为零行或不同表的最近更新时间明显错位，只能作为调查线索。零行也可能是授权、投放状态或上游报告窗口导致，不能直接认定为覆盖。

## 正式迁移候选

正式方案需要同时修改模型约束、四条 `_chunked_upsert` 调用、相关查询和 PostgreSQL 并发测试，不能只改 ORM 或只建索引。

候选目标键为：

- `keywords`: `(tenant_id, baidu_account_id, keyword_id)`
- `kw_report_snapshots`: `(tenant_id, baidu_account_id, report_date, keyword_id, device)`
- `keyword_region_reports`: `(tenant_id, baidu_account_id, report_date, keyword_id, region_name, region_level, device)`
- `keyword_hourly_reports`: `(tenant_id, baidu_account_id, report_datetime, keyword_id, device)`

`baidu_account_id` 目前可空。评审需在以下策略中明确选择：

1. 能可靠回填后改为 `NOT NULL`，再建立包含账户 ID 的普通唯一约束。这一方案最简单，但不能猜测多账户租户的历史归属。
2. 保留未归属历史，分别建立 `baidu_account_id IS NOT NULL` 与 `IS NULL` 的部分唯一索引，并让 upsert 根据归属走对应冲突目标。实现复杂，所有写入路径必须一致。
3. 若生产 PostgreSQL 版本和 SQLAlchemy/Alembic 支持并经验证，可评审 `NULLS NOT DISTINCT`；在版本确认前不能假设可用。

建议的受控顺序是：只读盘点 → 冻结相关同步 → 明确可回填与不可回填行 → 备份与校验 → 建立新唯一索引 → 切换 upsert 键 → PostgreSQL 双账户同外部 ID 验证 → 恢复同步。任何补采集或重新同步都应另行授权。

## 去重、恢复与回滚难点

- 当前旧键已经把潜在碰撞折叠为单行。数据库内没有足够信息恢复被覆盖账户的旧指标；需要可信备份、原始报告或经授权重新同步。
- 单账户租户的空账户行通常可以按唯一账户候选回填；多账户租户不能依据关键词文本、计划名或同步时间猜测归属。
- 新键启用后，不同账户可产生在旧键下冲突的并存行。回滚到旧约束会再次冲突，不能无损回滚。回滚前必须只读列出冲突组，并由业务负责人决定保留、归档或停止回滚。
- 资产表含人工维护的 `category`、`category_source` 等字段。若历史行被不同账户覆盖，不能在恢复时把一账户的人工分类复制给另一账户。
- 地域层级不能跨省、市相加；迁移验证应分别核对 `region_level`。小时数据还需确认 `report_datetime` 的时区语义保持不变。

## 启动 schema 评审前的确认项

数据库负责人需要明确确认：

- 生产 PostgreSQL 大版本、四张表现有真实约束及索引与代码是否一致；
- 实际多账户租户数量、每账户授权状态和最近同步时间；
- 百度 `keyword_id` 是否有官方或实测证据保证跨账户全局唯一；若没有，按可能碰撞处理；
- 上述只读检测的结果、潜在归属漂移和不可回填行数量；
- 是否有可用于恢复的原始报告、备份或合规的重新同步窗口；
- 空 `baidu_account_id` 的回填规则和多账户歧义行处理人；
- 迁移停机窗口、同步冻结方式、索引构建策略和可接受锁时间；
- 新键上线后的双账户同外部 ID PostgreSQL 测试、行数/金额核对与监控指标；
- 回滚条件，以及新键下已产生旧键冲突行时的处置方案。

以上项目确认并完成独立 schema 审核前，不应生成正式迁移或改变生产同步键。

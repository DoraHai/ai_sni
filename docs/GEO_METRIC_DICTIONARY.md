# GEO 指标字典与监测链路口径

> 解决「同一指标三套算法」：所有页面应优先调统一 metric service，不再各自现算默认窗。

## 时区

| 项 | 约定 |
|----|------|
| 存储 `captured_at` | **naive UTC** |
| 日历日 / 日指标 / 默认观察期 | **Asia/Shanghai** 转换后再取 `date` |
| 巡检配额窗口 | Asia/Shanghai（已有） |
| 日指标重算默认日 | `shanghai_today()`，不再用服务器 `date.today()` |

晚上 20:00 之后上海产生的样本计入**当天**日指标（不再掉到 UTC 次日）。

## 默认观察期

- **14 个上海日历日**（含今天），全局应统一。
- 全时段指标（如独立被引域名长尾）须在 UI 标注：**不受上方时间筛选影响**。

## 核心指标

### brand_mention_rate（品牌提及率）— 主 KPI

| 字段 | 定义 |
|------|------|
| 分子 | 可见性样本中 `mentions_brand=true` |
| 分母 | 可见性样本数（**排除** `is_brand_probe` 探测题） |
| 无样本 | **null**（未测），禁止显示 0% |
| API | `GET /api/v1/geo/metrics/brand-mention?tenant_id=&days=14` |

### brand_probe_recognition_rate（点名认知率）

仅探测题；不并入主 KPI。

### top1_rate（首选位率）

可见性样本中 `brand_position=first` 占比（同观察期、同剔除规则）。

## 样本构成（交付必显）

快照字段：

| 列 | 含义 |
|----|------|
| `sample_mode` | `manual` / `openai_compat` / `mock_persona` / `unknown` |
| `simulated` | `true` = 人设模拟，不可当真实引擎效果 |
| `patrol_run_id` | 所属巡检 run（人工粘贴为 null） |

报表统一展示：`真采样 N · 模拟 M · 人工 K`。  
**含模拟样本时交付摘要必须强制标注。**

## 巡检 ↔ 报表回路

1. 巡检落库写 `patrol_run_id` + `sample_mode` + `simulated`
2. `GET .../visibility-patrol/runs/{id}` 返回 `snapshot_ids`、`vs_previous`、`sample_composition`
3. `GET .../answer-snapshots?patrol_run_id=` 下钻原文

## 日指标

- 按上海日切 `captured_at` 聚合进 `geo_daily_metrics`
- 读取窗口缺行时应 **自动补算**（`ensure_daily_metrics_for_window`），客户界面不暴露「重算」

## 机器可读字典

`GET /api/v1/geo/metric-dictionary`

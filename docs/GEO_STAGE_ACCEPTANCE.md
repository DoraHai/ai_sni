# GEO 阶段验收建议

## 合 PR / 继续开发的放行标准

**以自动化为准，不强制浏览器端到端：**

```bash
# 1) 单测（GitHub Actions CI 同此命令）
python -m pytest -q tests

# 2) API 已起在 :8011，静态可选 :5176
python scripts/accept_geo_m1.py
```

两项都绿即可合 PR / 开下一刀。浏览器点击仅用于演示或排查 UI，不作为合并门槛。

Vue GEO 入口（权限 `geo.content`）：`/geo/overview`、`/geo/visibility`、`/geo/citations`、`/geo/competitors`、`/geo/evaluation`、`/geo/deliverables`。多引擎探测共用租户 LLM、按引擎人设模拟，确认后才写快照。

## 建议从哪一步开始验收

**从 Milestone M1「可见度闭环」开始做阶段验收**（脚本 `accept_geo_m1.py` 即 M1 自动化门禁）。

| 里程碑 | 范围 | 何时验收 | 入口 |
| --- | --- | --- | --- |
| **M1 可见度闭环（建议先做）** | Wave A→C + 渠道适配 + D0–D4 + 引用域名 + 正文抽 URL | 合并 PR #4、#5（及此前本地栈）之后 | 下文 M1 + `LOCAL_GEO_DEMO.md` §1–8c |
| **M2 标注提效** | C+ AI 标注建议 | M1 通过后、接 C+ PR | §8d / `GEO_CPLUS_SUGGEST_PLAN.md` |
| **M2b 期次对比** | 可见度 before/after + 拓词 vs 上次 | M1 通过后 | §8e / `GEO_PERIOD_DIFF_PLAN.md` |
| **M3 分发自动化** | 发布连接器 Phase 2（官网/文档 Webhook） | M1 通过后可并行验收 | §9 / `GEO_PUBLISHING_CONNECTOR_PHASE2.md` |

理由：M1 已覆盖「诊断 → 内容 → 门禁回填 → 可见度观测 → 引用域名」主价值环；C+/连接器是提效与自动化，不应阻塞主环验收。

## M1 验收清单（最小集合）

公共入口：先起 `8011` + `5176`（见 `docs/LOCAL_GEO_DEMO.md`）。

1. **内容闭环**：事实 CSV 导入 → 任务生成母稿 → 规则补丁 → 渠道稿 → 未就绪回填 400 → 就绪后回填成功  
2. **诊断桥**：诊断中心「创建 GEO 内容任务」打开编辑器  
3. **可见度**：登记快照（提及/竞品/情感）→ 竞品分析 / 评价分析有聚合  
4. **口径**：仅探测题时可见性提及率 = 未测；品类题分母不含探测题  
5. **引用**：正文含 URL → 抽取或保存 →「引用域名」有聚合；官网 `base_url` 可出自我有域引用率  
6. **门禁**：未核验/过期事实阻断发布；审校未通过不可回填  

全部通过后再开 M2（C+）或排期 M3（连接器）。

## M2（C+）抽检

1. 粘贴含竞品与评价倾向的回答 →「AI 标注建议」预填字段  
2. 人工改错后保存 → 竞品/评价页计数变化  
3. 「用 AI 探测」同样预填建议字段，未点保存前库中无新快照  

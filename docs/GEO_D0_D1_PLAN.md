# GEO D0/D1 · GeoLook 适配切片

> 状态：实现中 · 分支 `cursor/geo-d0-d1-geolook-adapt-e856`  
> 参考：`_refs/geolook`（gitignore）· `docs/GEOLOOK_COMPARISON_BRIEF.md`

## D0 提及率口径

- `geo_prompts` 增：`question_group` / `market` / `is_brand_probe`
- 创建时：问题含品牌名或组=「品牌验证」→ 自动标探测题
- `content-stats.visibility_mention_rate`：**排除**探测题样本；无可见性样本时返回 `null`（未测）
- 新增：`probe_recognition_rate`、`snapshots_visibility*`、`snapshots_probe*`

## D1 国内阵地权重

- vendoring：`app/geo/content/cn_blueprint.py`（CHANNELS_CN / CHANNEL_FITS / GROUP_PLAN）
- 首次 `GET /media-placements` 空库时种子 11 条 CN 阵地（带 P0/P1、引用量、why）
- `GET /channel-blueprint?group=` 按问题组推荐分发阵地并标注布局覆盖

## 验收

- [x] 仅探测题时可见性提及率 = null，认知率可算
- [x] 品类题 + 探测题混合时可见性分母不含探测
- [x] media 空租户自动种子含 ranking / official
- [x] `pytest` 含 `test_geo_d0_d1`
- [x] `alembic upgrade` 到 `0045_geo_d0_d1`
- [x] HTTP：prompts 建探测题 + stats；blueprint group=推荐；空库自动种子 11 阵地

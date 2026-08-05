# GEO 回答正文引用 URL 抽取

> 状态：可合并 · 分支 `cursor/geo-auto-cite-urls-21de`  
> 前置：Citation Insights（`cited_urls` 域名聚合）

## 目标

从粘贴/探测的回答正文中**确定性抽取** `http(s)` 链接，预填引用 URL，降低人工录入成本，喂饱引用域名看板。

## 非目标

- LLM 抽取 / 竞品情感自动标注（C+）
- 无协议裸域名猜测
- 第三方发布连接器

## 行为

- `extract_cited_urls_from_text`：正则 + 去尾标点；校验可解析域名
- `POST /answer-snapshots/extract-urls`：只返回建议，不写库
- `POST /answer-snapshots/probe`：附带 `suggested_cited_urls`
- 创建快照时若 `cited_urls` 为空，服务端自动用正文抽取结果回填
- UI：可见度页「从正文抽取 URL」；探测后自动填入

## 验收

- [x] 正文含多条 URL 时去重抽取
- [x] 探测草稿带回 suggested_cited_urls
- [x] 保存时 URL 栏为空仍可入库引用
- [x] pytest 覆盖抽取边界

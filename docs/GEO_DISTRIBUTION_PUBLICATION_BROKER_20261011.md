# GEO 中央核验与原生回写联调（2026-10-11，本地候选）

本批从 `beb7b468a7a6c256fee3d5ccc48409d3ec51f677` 接续，只新增联调测试与证据。原生
`app.geo.distribution_results.record_publication`、现有审核/事实/顾问门禁没有修改。
没有修改原程序、SEM、生产迁移或部署入口，也没有向平台提交文稿。

## 实际联调路径

使用 GEO 正确模型基线，动态加载中央候选真实 `distribution_contract`、`distribution_control`、
`distribution_scheduling`、`distribution_publication_verify`、`distribution_publication_results`
与 API router。原生登录 API 签发实名 JWT，不替换 `require_auth`；固定 `result_adapter('geo')`
直接导入真实 `app.geo.distribution_results`，没有模拟原生写入器。

每个场景经真实 HTTP/ASGI 路径完成：超管建立设备/账号绑定/日程策略 → 当前顾问启动项目 →
读取已审核原生稿 → 创建冻结发布任务 → 设备领取 lease → 设备提交模拟的 `HUMAN_PUBLISHED`
回执 → 顾问核验 → 原生回写 → 顾问任务列表读取结果。

顾问采用人工模式，三个必选确认项是公开可访问、目标账号、完整审核稿内容。测试提供的确认和
官方格式链接是模拟数据，**没有读取真实公开页，也没有验证任何真实平台账号**。
设备回执不是公开内容证明；只有经过顾问核验后才尝试原生登记。

## 七个新增场景

1. 真实中央核验创建 `GeoPublication`、`GeoMediaPlacement`、原生审计账本，并接上原生
   `publication_monitor` 的 `pending` 状态；`citation_national` 保持空，不伪造引用或健康结果。
2. 同请求幂等回放、变更 payload 冲突、不同请求重复核验与已写回结果的显式重试，都只有一个
   原生 publication/placement；首次原生写入改变 `variant.updated_at` 后不会导致后续中央核验误报。
3. 项目已暂停时，六个并发核验真实串行入账，保存六次中央核验但只有一组原生结果。暂停保留
   历史结果登记能力，不能因此新建或执行发布。
4. 回执之后撤销原生客户审核：中央保留顾问核验记录，但原生 writeback 标为 `blocked`，没有
   publication/placement/原生账本；显式重试仍不能绕过审核。
5. 在真实原生流程最终审计 INSERT 注入 PostgreSQL trigger 故障：publication、placement、
   监测、variant/task 状态以及原生账本整体回滚；中央核验和 `pending` 记录保留。解除故障后
   显式 retry 只登记历史结果，使用原 event_id，不新增任务、不重新派发、不再次提交文稿。
6. 实际 JWT 检查三个确认项、禁止正文透传、其他顾问/超管/设备鉴权、跨客户/项目与实时权限撤销；
   `GET /tasks` 只返回核验与写回摘要，无正文、设备凭证、内部 payload、grant/lease 和请求指纹。
7. `unknown` 结果拒绝核验入账，中央核验/写回和原生结果均为空。

原生事实卡、已审核稿、品牌与发布规则通过真实数据库数据构造；没有 mock 审核、事实或顾问
授权。旧来源/监测回归中的明确测试替身仍存在，不能把这些单元回归称为真实平台验收。

## 数据库隔离

只使用自有 PostgreSQL `127.0.0.1:55507`，数据库/用户 `geo_ci`。数据库 helper 强制检查
driver/host/port/database/user，不读取生产连接。每个场景只在随机
`geo_results_test_<32 hex>` schema 建表；原生独立结果 DDL 与中央三份独立 DDL 均在该 schema
执行，结束清理。原生租户策略需要的空 `public.demo_tenant_bindings` 注册表也仅位于此自有测试库。
共享中央 55443 实例未使用。测试结束后停止本批 55507 自有实例。

## 测试与绑定证据

- 新增联调：**7 passed，0 failed，0 skipped**。
- 冻结前完整回归：**72 passed，0 failed，0 skipped**，包含新增 7、原生结果 34、来源 PG 8、发布门禁 1、
  监测单元 22。
- 最终 XML：系统 TEMP `geo-distribution-publication-broker-regression-20261011.xml`。
- 最终 XML SHA256：`193f7e5dcd8928d411e41814e3ca9962fca1df71b1623b785b5a552235614250`。
- 测试文件：`tests/test_geo_distribution_publication_broker_postgres.py`。
- 逐文件 SHA256：`docs/GEO_DISTRIBUTION_PUBLICATION_BROKER_EVIDENCE_20261011.json`。

72 项回归当时中央存在同一轮工作台开发的未提交改动，因此历史证据绑定实际测试文件 SHA256。
中央随后冻结为干净提交 `729af3c4071d6f410ef12ecb88de6ca6a3559f13`，针对其后端变化补验新增 7 项：
**7 passed，0 failed，0 skipped**，没有重复计入新的独立用例总数。原生 adapter/DDL 与全部测试文件
保持不变。冻结代码的静态页面匹配仅返回 `needs-human`，不产生核验凭证或原生回写；本批人工核验
联调没有将此静态初检视为机器核验。

- 冻结后 XML：系统 TEMP `geo-distribution-publication-broker-frozen-729af3c4-20261011.xml`。
- 冻结后 XML SHA256：`0c4f641eb28e485aaa48f69b15d5abac854525e285caa196cd5498ab6ea7089c`。
- 冻结 API SHA256：`e946326f0c3c444e55245cb4ca6f30277c2f9293b64f2d19d32bf60353380001`。
- 冻结 results SHA256：`44dde77dc352e58f3efd083b2c4d2bf6996f2339410326def40652adca61721b`。
- 冻结 verify SHA256：`281c8fc92c64e3b2b08cafb827c9596f833a934fdb90180997752192ed59dc5c`。

测试前后核对上述 hash 未变；随机测试 schema 剩余 0，自有 55507 实例已停止。

## 验收边界

本批证明本地真实 JWT、router、PostgreSQL、原生写回与监测登记衔接。没有生产 DDL/部署、真实公开页
抓取、真实账号身份识别、编辑器填稿上传、自动最终提交或平台首次发布时间证明。
登记时间仍来自回执 `reported_at`；监测 `pending` 仍需真实观测，不能代表 AI 曝光/引用。
SEM 的 AI 接管继续关闭，按用户要求最后推进。

# oCPC 目标转化出价修改

在投放管理的 oCPC 策略卡增加「修改出价」。只修改既有目标转化成本模式策略的 `ocpcBid`；不修改模式、绑定计划、转化目标或深度出价。

接口文档：`/Users/daisy/Documents/需求/ai产品/需求清单/baidu-dev-docs-markdown/pages/0289-搜索广告投放-oCPC投放管理-更新oCPC出价策略-100609.md`。调用 `OcpcService/updateTargetPackage`，只发送 `targetPackageId` 和 `ocpcBid`。

## 使用及执行边界

- 实名用户须有 `manage.ocpc` 编辑权限。金额 0.01～9999.00 元，最多两位小数，单次变化不超过 20%。
- 默认演练：`BAIDU_OCPC_WRITE_ENABLED=false`，只记录行动台账，不访问百度、不改变本地价格。
- 真实执行还需全局开关允许、关闭旧确认协议、当前客户和账户明确授权 `ocpc_bid`，并满足客户调价幅度及每日次数限制。新增 scope 不会自动给现有账户授权。
- 真实提交采用现行后端的本人一次确认和幂等请求键，绑定账户、策略、旧价、新价。保留行锁、持久化执行意图、执行前权限和远端价格复核；结果不明进入人工对账，禁止直接重试。
- 本次上线不改变任何生产真实写入开关或客户授权，不迁移数据库、不部署其他模块。

## 发布隔离

前端基于 `codex/production-sem`，后端基于 `codex/production-sem-backend`。仅移植本功能补丁，不以旧 SEM 分支覆盖后端鉴权和回写文件。

前端使用 `frontend/scripts/deploy-sem.sh`；后端按 `.github/workflows/production-sem-backend-deploy.yml` 的提交归档范围打包，通过服务器已有的 `platform-deploy apply sem` 发布。发布必须核对远程分支 HEAD、干净提交、归档 SHA256、健康接口和发布提交一致性。后端发布脚本健康检查失败会自动回滚。

## 验证

- oCPC 单元测试覆盖演练不联网、租户权限、旧价变化、独立开关、账户授权撤销、唯一确认、执行意图、未知结果对账。
- 运行后端发布工作流列出的测试及 `tests/test_ocpc_bid.py`、`tests/test_sem_live_write_policy.py`。
- 前端运行 oCPC 和现有组件、行动台账等检查，并运行生产构建和 `verify:sem-build`。
- 测试使用 mock，无真实百度调价；真实资金操作及 PostgreSQL 并发实测不在本次演练上线范围内。

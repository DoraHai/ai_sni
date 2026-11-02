# P10百度批量模板摸底（2026-10-28，Asia/Shanghai）

**内部演练/不可上传百度。**本轮只读公开官方资料，没有登录百度客户账户，没有调用百度业务API，没有获取或上传客户物料。
未拿到当前搜索推广官方批量导入模板原文件，禁止据API字段、历史文章或后台报表猜造表头。

## 公开官方证据

1. [百度智能云《搜索推广API》官方PDF（页面日期2021-12-22）](https://bce-cdn.bj.bcebos.com/p3m/pdf/bce-doc/online/SEM/SEM.pdf?timeStamp=1629849600124)：本轮直接下载到TEMP并提取正文，含推广管理服务概览、Account/Campaign/Adgroup/Keyword/Creative/NewCreative及BulkJob等服务。它证明历史API服务概念，**不证明当前可上传文件格式或账号可用性**。
2. [百度凤巢《推广锦囊》](https://fengchao.baidu.com/nirvana/nirvana-asset/resource/html/managementkits/index.html)：可公开读取，含地域、时段、创意/样式等推广管理介绍；没有据此取得当前导入模板及精确表头。
3. [百度营销商业开发者中心](https://dev2.baidu.com/)：公开读取返回动态空壳，未取得具体规范正文；标为“待核实”，不据页面标题推断能力。

仅采纳上述官方来源。搜索出现的第三方教程、代理商营销页、百度经验用户投稿不作为当前官方模板证据。
旧资料可能已过时，以下“历史API已证实”不等于“当前批量文件已证实”。

## 分项结果

| 对象/设置 | 本轮已证实的范围 | 当前批量新建/修改文件及精确字段 |
|---|---|---|
| 推广计划 | 官方历史PDF列CampaignService的get/add/update/deleteCampaign | **待核实**：新增导入能力、模板版本/表头、初始暂停、父级映射、数量限制 |
| 推广单元 | 官方历史PDF列AdgroupService的get/add/update/deleteAdgroup | **待核实**：批量新增模板、计划关联、出价/URL覆盖、初始状态 |
| 关键词 | 官方历史PDF列KeywordService的get/add/update/deleteWord | **待核实**：导入模板、匹配枚举、出价口径、PC/移动URL、限量及错误回执 |
| 基础创意 | 官方历史PDF列CreativeService的get/add/update/deleteCreative | **待核实**：当前基础创意模板、标题/描述/URL列、字数计数、数量与审核状态 |
| 高级创意 | 官方历史PDF列NewCreativeService的Sublink/Phone/Ecall等历史服务；另列DynamicCreativeService | **待核实**：当前每种高级创意的批量文件支持、挂载层级、字段、素材规格、绑定/解除及回执；不能用基础创意替代 |
| 否词 | 官方历史PDF的CampaignType、AdgroupType均有普通否词与精确否词属性；仅为历史API属性证据 | **待核实**：当前账户/计划/单元范围、精确/短语类型、批量文件添加/替换/删除行为与限量 |
| 预算 | 官方历史PDF的CampaignType有每日预算，文中另说明周预算；不据此断言当前文件字段及硬控能力 | **待核实**：账户/计划日额或总额导入能力、金额单位、预算下限、当前帽、继承/覆盖；内部关键词预算仅测算 |
| 地域 | 官方历史PDF的CampaignType有地域列表及继承账户地域说明，并附历史地域代码 | **待核实**：当前批量文件支持、最新地域编码、意图口径及继承；不把旧代码当当前可上传值 |
| 时段 | 官方历史PDF的CampaignType包含推广**暂停**时段，不能直接当作本契约的投放时段 | **待核实**：当前批量文件支持、时区、时间粒度、投放/暂停转换、跨日/日期边界及继承 |

BulkJobService官方历史介绍涉及整账户下载/异步请求状态等，不能当作上传导入服务。
本轮没有已证实的**当前正式上传模板**；全部正式导出保持关闭。

## 合成样例和下一次核实入口

`synthetic.internal.json`包含完全虚构的计划→单元→关键词/基础创意关系，只有内部字段，无百度表头；预算12345分也是人为合成值。
高级创意、否词、地域/时段等未证实项保留待核实清单，不填虚构可执行行。
`app/sem_phase0/templates.py`可复现生成；只接受`.json`输出，`export_baidu_execution_file`无条件拒绝。

后续获准进入1a后，以当时官方公开规范或获准取得的当前模板原文件逐类核实：版本/hash/下载日期、原表头/枚举/计数、初始暂停、依赖ID、错误行/部分成功和回执字段。
核实和演练均须保持正式出口关闭；真正执行仍须1b-P单独放行及完整客户确认。
本次不联系客户、百度或其他人索取模板，不因待核实而外推支持范围。

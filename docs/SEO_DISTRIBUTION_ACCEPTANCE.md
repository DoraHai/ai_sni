# 国内分发与外链统一验收

## 能力范围

- 12 个国内浏览器渠道保留适配稿、材料包、填稿助手、链接回收。
- 百家号、头条号、搜狐号本机执行器增加批次确认、可识别分类/封面控件、远端图片确认、草稿恢复地址及作品行状态回收。未知编辑器结构停止当前任务，继续其他任务；本机登录信息不上传。
- 公众号保留官方草稿和发布状态流程。
- 抖音、快手新增独立视频面板：应用连接、用户 OAuth、刷新、MP4 上传、人工确认提交、作品查询。上传与发布前持久登记，失败不自动重发。视频处理链独立于长文适配。
- 提交中断且作品 ID 丢失时，可录入官方后台的作品 ID；查询当前账号并核对标题后恢复关联，再同步审核结果，恢复过程不重复发布。
- 外链支持竞品样本过滤、SEO 跟进任务、真实外链增长完成证据、分发地址关联、用户报表引荐访问/转化及外部查询调用预算。

## 统一真人验收（尚未执行）

1. 使用测试账号各走一次三平台编辑器：空稿、多图、封面、分类、保存草稿、重启恢复、修改后拒绝覆盖、提交、审核中、审核失败、发布后链接回收。浏览器真实 DOM 与模拟夹具不同处，以现场结果修复；不宣称已验证稳定兼容所有后台版本。
2. 抖音应用需要 video.create 和 video.data，快手需要 user_video_publish 和 user_video_info。将回调配置为 `https://gsnipers.snipers.com.cn/seo/distribution`。由账号持有人在官方授权页同意，应用密钥仅在服务端加密保存。
3. 各上传一条已审核内容对应的测试视频：抖音不超过 48 MB，快手不超过 8 MB；快手封面 JPG/PNG 不超过 3 MB。核对标题、素材、账号后逐条确认发布，记录作品 ID 并查询审核状态。
4. 验证授权拒绝、过期、刷新令牌轮换、网络超时、平台驳回；不确定提交不能直接重发。快手上传网关只用 HTTPS，不降级明文；需确认账号返回的网关支持 HTTPS。
5. 开启已采购的外链索引，核对一次单站和竞品样本查询。每日调用额度含失败及中断预留；没有实际账单数据时金额显示未知。此步骤会产生供应商费用，留待集中验收。
6. 从机会建任务，录入跟进；没有新外链抓取证据时完成应被拒绝。真实新链接核实后指标增长才可完成。检查不同租户隔离。
7. 回收真实发布链接并发现外链，将分析平台同期间报表录入，确认未知访问不展示为零，用户提供的数据明确标注来源及日期，不作为自动抓取证明或因果归因。

## 统计与契约

新指标 `seo.backlinks.verified_count`：当前网站 active 且最近一次抓取 state=found 的来源页面/目标页面唯一外链数量。索引候选不计入。沿用原 trend_7d 结构，历史不足返回 null。只有 seo.links 查看权限者在快照中获得此项；原五项权限要求保持不变。

任务新增 action_type=backlink_outreach，params 包含来源 URL/主机名、可选机会请求 ID 和最多 100 条跟进。完成证据指向该来源主机、任务创建后首次发现并抓取确认的新链接，同时要求真实指标增长。共享任务字段和状态不变。

分发效果展示最近 200 条有地址的发布记录。访问及转化录入按来源 URL 保存最近一期报表（最多 500 个来源），标记 user_reported，独立于抓取证据。

## 官方接口依据

- [抖音授权](https://open.douyin.com/platform/resource/docs/develop/permission/web/oauth2)
- [抖音上传](https://open.douyin.com/platform/resource/docs/openapi/video-management/douyin/create/upload/)
- [抖音发布](https://open.douyin.com/platform/resource/docs/openapi/video-management/douyin/create/create-video)
- [抖音作品数据](https://open.douyin.com/platform/resource/docs/openapi/video-management/douyin/search-video/video-data/)
- [快手用户令牌](https://open.kuaishou.com/platform/openApi?menu=13)
- [快手上传与发布](https://open.kuaishou.com/platform/openApi?menu=20)
- [快手作品查询](https://open.kuaishou.com/platform/openApi?menu=22)

抖音作品接口只返回可见作品，查询缺项保留待核实。快手 play_url 是流媒体地址，不计为外链或公开文章。应用获批、用户授权和现场审核结果均不能由模拟测试代替。

# 指标验收面板本地浏览器测试

从仓库根目录运行 `node frontend/tests/local-geo-evidence/server.mjs`，打开 http://127.0.0.1:5278/tests/local-geo-evidence/index.html 。

挂载真实GeoEvidenceTasks组件，所有请求由内存adapter处理，不连接生产。按顺序选择任务→采集基线→选择官网发布记录→核验发布→启动复测→核验完成。最终一步模拟409，任务应保持进行中。切换客户应清空详情。测试后Ctrl+C关闭服务器。

浏览器实际验证以上动作和页面布局通过；并发、错误和分页自动化见geo-evidence-controller.test.mjs。此页面不构建进生产产物，也不证明真实发布或完整周效果。

国内平台本地执行器（真人验收前的试用版）

支持百家号、头条号、搜狐号。它复用工作台导出的 JSON 任务包。
其他平台继续使用原浏览器填稿助手。模拟编辑器通过不代表平台真人账号已验收。

安装 Python 3.11+，在解压目录执行：
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python runner.py tasks.json

素材上传：将 JPG/PNG 放入 images/任务ID/，添加 --images images。
只上传你明确放入此目录的图片，不自动从任务 HTML 下载任何 URL。
每篇最多 20 张，单张 3 MB、合计 12 MB；图片交给上传控件后仍需确认完成和位置。
需要在每个平台登录并打开空白编辑器；遇到无法识别的控件会停止，不猜测点击。
文字、素材就绪后人工核对封面、分类、原创/AI 声明，输入 draft 可保存草稿。
添加 --publish 才允许逐篇输入 publish 后点击发布。默认不会提交文章。
点击发布不等于发布成功；平台二次确认、验证码和审核须人工处理。
发布后回填公开链接，结果文件可回收到工作台；服务端仍会核验公开页面。

本机 ~/GSnipersPublisher 保存账号隔离浏览器 profiles、journal.json、results.json。
不要上传或分享 profiles，它包含登录状态；不要将这些文件放进代码仓库。
已尝试发布的任务重跑时只核实结果，不再次提交。异常终止后检查平台和 journal，
确认没有进程运行才手动删除 runner.lock。结果不明时不要删除 journal 重新发送。
图片上传入口、封面、分类及审核状态各平台仍需要真人验收，当前不承诺无人值守。

故障处理：单个账号浏览器启动或关闭失败不再中断其余任务。每篇处理后保存
run-report.json，区分已记录公开链接、待人工处理和失败；存在失败时程序退出码为 1。
“已记录链接”不代表爬虫已经核实发布成功，仍应回到分发工作台完成链接核验。
同源 about:blank/srcdoc 编辑器可以填入，跨域及没有同源权限的沙箱编辑器不处理。
图片控件兼容 MIME 类型和 .jpg/.jpeg/.png 扩展名声明，只选择接受本次全部素材的唯一入口。

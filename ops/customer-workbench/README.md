# 独立客户工作台发布准备

2026-10-08。本目录仅提供本地制包工具和 Nginx 候选片段，没有上传、迁移、切换或重载动作。当前开发仍在草稿 PR #592；SEO 后端在 #593。生产合并和部署另需确认。

## 制包

在工作区无未提交变更、前后端版本已冻结且依赖已安装后运行：

```powershell
node ops/customer-workbench/package-release.mjs <完整40位提交SHA>
```

默认输出到操作系统临时目录的独立新目录。产物包含 tgz、SHA256SUMS 和 release-summary.json。tgz 只装入 customer-workbench/index.html、app.js、app.css、release-manifest.json；凭据、测试夹具和源码不入包。脚本验证当前提交、干净工作区、文件集合及清单中的逐文件哈希；构建复用已有会话与登录代码。

局部工具测试：`node --test ops/customer-workbench/package-release.test.mjs`。通过工具测试不等于生产登录、Nginx 配置或上线验收通过。

## 同域入口与待落实事项

目标入口为现有域名下 `/customer-workbench/`，继续使用现有 `/login` 与 `/api/v1/`，无需增加域名或独立登录。候选静态目录为 `/opt/customer-workbench/releases/<完整SHA>`，current 指向被批准的版本。

`customer-workbench.nginx.conf.example` 是候选 HTTPS server 内片段，尚未经过目标服务器的 `nginx -t`，不能直接当作已生效配置。只允许首页、app.js、app.css；其他路径返回404，清单保留在发布目录供管理员核验。

现有 platform-routes 部署走完整候选配置及固定哈希校验，不能临时往服务器配置里插片段绕过。实施前需由总控与服务器负责人核对：

1. 当前生效的站点配置、include 布局与受限发布模块版本；将候选路径正式纳入已有 Git 跟踪和发布校验。
2. 静态制包的完整 SHA、哈希、只读文件权限及 previous 回退目录；首次安装没有 previous 时保留原入口。
3. SEO 后端版本、0105正式迁移计划及备份、新表运行账号权限、顾问与客户的分配配置。此制包工具不执行数据库操作。
4. 用户确认合并/部署顺序后，先让静态地址可访问，再启用宿主入口；避免先出现失效链接。生产分支推送可能触发自动部署，准备阶段不推生产分支。

## 上线后必要验收

- 未登录访问工作台回到现有登录，登录后回到原工作台路径；真实验证码由可操作的账号持有人完成。
- 普通客户与已分配顾问各验证一次对应客户/站点；无权限及撤权后不显示旧客户内容。
- 一篇带图稿件读取/放大、一条确认与版本保护流程；真实业务确认需获准对象，不能用生产客户随便试写。
- 返回列表保留筛选，移动端可阅读。客户确认不触发发布。
- 失败时撤入口/回退静态 current，后端按兼容方案回退；不删除确认与审计记录，不自动降迁移。

当前隔离环境验证不能替代以上生产入口验收；此文档也不声称消息沟通已经上线。

## UI15入口接线与构建（2026-10-08）

宿主 `frontend/src/views/workspace/AcquisitionCockpitView.vue` 已接入客户工作台链接：需要当前登录、非演示、SEO可用、明确的有效tenant/site与active网站；地址只携带这两个范围参数，目标应用仍独立鉴权。加载时无凭据GET探测同域新页面，5秒超时；只有收到新工作台HTML才显示入口，旧SEM壳或404不展示死链。上线后旧页面需刷新以重新探测。

`.github/workflows/customer-workbench.yml` 在PR和生产分支变更上生成精确SHA的独立产物并校验身份/范围/制包契约；工作流只有contents:read，无部署账号或生产操作。原SEM构建/发布继续管理宿主链接，本工作台没有混入SEM构建包。

服务器负责人先运行本目录 `server-readiness.sh`（bash；只读；不读.env），或逐条回传以下输出：

```bash
sudo /usr/local/sbin/platform-deploy status
sudo sha256sum /usr/local/sbin/platform-deploy /etc/platform-deploy/modules/platform /etc/nginx/conf.d/gsnipers.conf
sudo nginx -t
readlink /opt/sem-frontend/current
readlink /opt/auth-frontend/current
readlink /opt/customer-workbench/current
```

最后一个路径不存在时记录尚未创建，不自行创建。当前仓库的platform模块只接受platform-routes包，不能把工作台静态包直接传给它。待实际模块版本确认后，在既有受限发布机制内增加对应静态包支持并审核；不借用root手动拷文件替代。此前的Nginx片段仍为候选，没有生产激活。

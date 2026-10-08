# 独立客户工作台发布准备

2026-10-08。本目录提供本地制包工具、受限静态发布处理器和 Nginx 候选片段。本轮仅实现、测试，未执行上传、迁移、线上切换或重载。当前开发仍在草稿 PR #592；SEO 后端在 #593。生产合并和部署另需确认。

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
3. SEO 后端版本、0105/0106正式迁移计划及备份、新表运行账号权限、顾问与客户的分配配置。此制包工具不执行数据库操作。
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

## 已取得的服务器基线

2026-10-08总控已通过既有SSH连接完成只读核对，用户无需转发清单。platform已启用，nginx -t通过；SEM current=e494ea936dbd，Auth current=63c67f379cc8；customer-workbench/current尚不存在。现网Nginx SHA256=d710448c24f61e14c0e69a5c2636987781b09042a3a72cd7a11605d316ad12f3，dispatcher SHA256=0330e2c14f2ff7074df140e02d56136aa2a5248ebce296d9c35007437c09937a。未修改服务器。

## 既有发布入口扩展（待批准实施）

`ops/platform-deploy/install-platform-routes.sh --enable` 增量安装现有platform模块及root所有的customer-workbench.py，先校验dispatcher版本并备份。安装不改Nginx、不激活页面、不迁移数据库。

静态包继续经已有 `publish-platform-routes.sh` 上传与 `platform-deploy apply platform` 边界，新增第四参数 `customer-workbench`；原三参数调用仍发布routes。只接受当前production-sem完整SHA、固定目录及四文件包，校验清单/逐文件哈希并锁定发布，原子切换current；失败恢复旧current，首次失败移除新current。没有新域名、第二套登录或生产数据库访问。

批准后的顺序：

1. 确认SEO代码与0105/0106迁移兼容、备份与新表权限；数据库操作仍由单独批准的计划执行。
2. 合并精确版本并等待现有CI；安装本次受限模块扩展。
3. 从干净的production-sem精确SHA制包，通过既有publisher第四参数customer-workbench部署。初次路由未启用时返回staged-awaiting-route，仅表示文件已准备。
4. 手动触发 `Production SEM platform routes` 工作流（production-sem）。路线配置新增五个精确静态location；成功需原SEM路由和三个新静态文件逐字节核对通过。失败恢复原Nginx配置。该工作流push只验证/制包，生产激活仅workflow_dispatch，避免文件未就绪时自动改路由。
5. 生产登录及普通客户/已分配顾问范围验收后，宿主刷新将显示已探测可用的新入口。

静态文件已有路由时，后续静态发布也核对线上三个文件，失败回退；不改变Nginx或其他服务。服务器生产head在上传前后和受限入口再次核验，不发布草稿分支包。临时上传包可能保留供人工按发布记录清理，不自动删除审计记录。

回退：首发路由失败自动恢复原配置，静态文件可保留为未公开产物；静态更新失败自动恢复previous。若需人工回退，由发布负责人按记录恢复指定已核验静态链接或配置备份，不拼接旧新文件。后端仅回退到兼容现有schema的版本，不能把旧版0104健康检查会拒绝0106说成安全回退。

本机Windows会跳过Linux发布状态机测试；以PR上的Linux测试结果作为该部分依据，不能把跳过计为通过。生产验证码和最终入口验收仍待上线窗口，不用反复重跑隔离业务写入。
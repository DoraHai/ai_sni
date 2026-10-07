# 独立构建与发布准备

2026-10-07，UI-07版本归档。拟定同源 `/customer-workbench/`，本轮只做本地提交，不部署。

## 构建

在仓库的 customer-workbench 目录执行：

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run build
```

使用Node 24，Vue精确锁版本3.5.42与同工作树 frontend/package-lock.json 对齐；source-map-js两侧锁为1.2.2。2026-10-07按总控明确授权同时更新两侧package/lock安全补丁，使用正常npm解析生成integrity，不修改宿主业务或关闭扫描。scripts/build.mjs 固定读取 `../frontend`，不接受个人绝对目录配置。直接import既有 session.js/sessionStorage.js/loginRedirect.js，无独立登录体系或token存储。构建拒绝宿主会话/lock脏改、Vue锁不一致和演示模块入图；本产品源码在提交前可构建但manifest标记sourceTreeClean=false，提交后重建应为true。

| 产物 | 用途 |
| --- | --- |
| dist/customer-workbench/index.html | 独立生产入口 |
| dist/customer-workbench/app.js | 页面与同仓库既有会话源码打包结果 |
| dist/customer-workbench/app.css | 基础与连接页面样式 |
| dist/customer-workbench/release-manifest.json | 同仓库Git SHA、源码干净状态、会话/独立输入/lock与产物hash |

只交付以上四文件；不包括tests、演示入口、node_modules、历史文档、检查点、截图、源码映射或任何凭据。构建只写本目录dist的文件白名单，不递归删除外部目录；发现额外旧文件时拒绝覆盖。文件名未带hash，生产不能用长期immutable缓存。

## 相关验证

- `npm run test:contracts`：只读与workflow契约、计划控制器、宿主范围及登录边界。
- `npm run test:connected`：UI-05完整DOM链路、401/403/409及身份/范围迟到响应。
- `npm run test:ui06`：pretest先构建，再测分页/七组合/错误重读和编译产物原会话/原登录路径。
- `npm run test:ui08`：pretest先构建，测试四类执行链DOM、处理权限、报告真实下载/hash、周期显式保存、错误和迟到范围变化。
- `npm run test:ui09`：准确正文来源/版本保护、编辑审核DOM、发布只读与禁止旧入口、冲突/权限/未知结果门禁。
- `npm run test:ui10`：AI授权和同站点资料/关键词选择、四类独立触发、准确版本人工登记与逐记录资格、未知结果只读核对。
- `npm run test:demo`：保留的本地演示；puppeteer已改成本目录锁定依赖。
- `git apply --check customer-workbench/docs/host-entry.patch`：在仓库根核对入口建议补丁，不能视为已应用。

浏览器使用本机Edge；其他系统通过EDGE_BINARY指向兼容的本机Chromium。测试均用假身份和本机内存服务器；编译产物测试拦截虚拟HTTPS源并转到127.0.0.1，不连接真实域名、账号或客户数据。

## 发布待办（本轮未执行）

1. 总控审查本地提交与入口补丁，安排源码推送/PR/合并。
2. 确认目标SEO新版本、0105、顾问active分配及双edit资格；安排普通实名试点验收。
3. 按现有仓库发布流程适配独立发布单元和同源静态路径，四文件原子切换/回滚；不得手工覆盖线上散文件。
4. 原工作台入口补丁只在独立页面可用后启用，避免死链。沿用既有/api、/login代理，不改其他模块路由。
5. 正式发布必须从准确提交重新构建，检查manifest sourceTreeClean=true和哈希，保留提交与产物对应关系。

无部署脚本、路由注册或原组件改动混入本提交。后续SEM/GEO接口接入另列范围，不借机启动其自动化。更早开发记录位于docs/history，历史路径不参与当前构建。

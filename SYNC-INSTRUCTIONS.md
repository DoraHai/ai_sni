# 本地环境同步说明(给所有参与开发的 AI 会话/开发者)

## 这是什么

`codex/production-sem` 是一个新推送到 GitHub 的分支,内容和生产服务器
（`101.200.193.83`）现在实际运行的代码**做到了逐字节一致**：

- `app/`、`migrations/`（后端源码，真实可编辑）
- `frontend/dist-snapshot/sem/`、`frontend/dist-snapshot/auth/`、`frontend/dist-snapshot/geo/`
  （三个前端**当前构建产物**的原样冻结快照，不是可编辑源码，见下方"重要限制"）

仓库地址：`https://github.com/DoraHai/ai_sni.git`
分支名：`codex/production-sem`

**从现在起，任何新的开发工作都应该从这个分支开始，不要再从自己本地旧的工作目录继续改。**

## 怎么同步

如果你本地已经 clone 过这个仓库：

```bash
git fetch origin codex/production-sem
git checkout codex/production-sem
git pull
```

如果你本地有未提交的改动，**先不要 `git checkout`**，防止丢失工作——先把本地改动
提交到自己的分支或者 `git stash`，再切换过去对比，确认哪些改动还需要重新应用。

如果你本地还没有这个仓库：

```bash
git clone -b codex/production-sem https://github.com/DoraHai/ai_sni.git
```

## 重要限制：前端快照不是能直接改的源码

`frontend/dist-snapshot/` 下面的内容是**压缩打包后的产物**（`.js`/`.css` 都是 minify 过的），
不是 Vue 源文件。**不要在这个目录下面直接改代码**——改了也没法维护，下次一构建就会被覆盖。

这三个前端目前存在的已知问题（详见仓库根目录 `CLAUDE.md` 铁律 0）：
- 生产环境这份构建产物的来源已经和 Git 历史脱节，找不到对应的可编辑源码提交
- 如果你本地环境里刚好保留着能产出这份界面（尤其是橙色主题、`sem-morning` 变体）的
  真实源码，**这个非常重要，请立刻联系项目负责人**，把你本地那份源码也做成一次干净提交推上来——
  目前全仓库范围内，只有"构建出来的产物"，没有任何地方保留着对应的源码

## 接下来正常的开发流程（从这个分支开始，之后都按这个来）

1. 从 `codex/production-sem` 切一个新分支做你的功能，比如 `feat/xxx`
2. 只改这个功能真正需要的文件，不要顺手改其他模块（SEM/SEO/GEO/门户边界不要跨）
3. 前端改完必须 `npm run build && npm run verify:sem-build` 通过
4. 通过 `frontend/scripts/deploy-sem.sh`（或对应服务的部署脚本）部署，不要手动 scp/改
   `releases/` 目录里的文件
5. 涉及 `app/baidu/writeback.py`、`app/security/*`、`app/main.py`、`app/api/auth.py`
   这几个文件时，先看 `CLAUDE.md` 铁律 3 那张表，确认没有把已有的安全机制改掉
6. 改完发 PR 合并回 `codex/production-sem`（或团队约定的主分支），不要各自为战、互不合并

## 一句话总结

**以后大家的本地环境，都从 `codex/production-sem` 这个分支开始工作，改完的东西要合并回来，
不要再各自抱着一份本地代码各改各的、直接发布到服务器——这就是今天出问题的根源。**

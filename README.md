# Growth Sniper AI 获客平台

Growth Sniper AI 是一个由 FastAPI、PostgreSQL、Vue 3 和 Vite 构建的 SEM + GEO 运营平台。

**使用说明（按模块）**：[`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)  
**GEO 详细操作手册**（开户 → 事实核验 → 写稿禁编造 → 竞品溯源 → 交付口径）：[`docs/GEO_OPERATOR_GUIDE.md`](docs/GEO_OPERATOR_GUIDE.md)

## 项目结构

- `app/`：FastAPI 后端服务
- `frontend/`：Vue 3 前端应用
- `migrations/`：Alembic 数据库迁移
- `scripts/`：开发验证、运维与数据处理脚本
- `deploy/`：服务器部署配置和说明
- `tests/`：后端自动化测试

## 本地启动

### 1. 启动数据库

```bash
docker compose up -d postgres
```

### 2. 启动后端

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

请按照实际开发环境填写 `.env` 中的配置。不要提交 `.env`、API Key、Token 或数据库密码。

### 3. 启动前端

打开另一个终端：

```bash
cd frontend
cp .env.example .env.development
npm ci
npm run dev
```

## 团队协作

不要直接在 `main` 分支开发。开始新任务前，从最新的 `main` 创建功能分支：

```bash
git switch main
git pull --ff-only
git switch -c feature/your-feature
```

完成后推送分支并在 GitHub 创建 Pull Request：

```bash
git add .
git commit -m "feat: describe your change"
git push -u origin feature/your-feature
```

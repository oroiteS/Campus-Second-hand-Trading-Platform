# campus_backend —— 校园二手交易平台后端

Flask 应用工厂 + 蓝图分层。依赖方向（flask-backend 规范，单向）：
`main → app → router → routes → services → model`；横切件在 `src/common/`
（统一响应、错误码表、分页助手、Swagger 装配）。端内总纲见
`docs/plan/backend/00-骨架与契约.md`。

## 目录

```text
campus_backend/
├── main.py               # 仅入口：import + main()（app.run）
├── .env / .env.example   # 应用配置（不入 git）/ 模板（入 git）
├── migrations/           # flask-migrate（Alembic）迁移脚本
├── src/
│   ├── app.py            # create_app()：扩展初始化、注册路由与错误处理
│   ├── config.py         # 唯一读环境变量处
│   ├── model.py          # db = SQLAlchemy() + prefix() + 全部 ORM 模型
│   ├── router.py         # 唯一蓝图注册处（/api 前缀）
│   ├── common/           # 横切件：responses / errors / pagination / swagger
│   ├── routes/           # web 层：每资源一文件，导出 bp
│   └── services/         # 业务层：业务逻辑 + 数据库操作
└── tests/                # pytest，与 routes/services 对应
```

## 环境准备

- Python 3.12 + uv；依赖已在 `pyproject.toml` 全量声明，**禁止安装清单外包**。
- 复制 `.env.example` 为 `.env` 并填写（存储凭据取自仓库根目录 `.env`）。

```bash
uv sync        # 仅恢复已声明依赖
```

## 启动

```bash
uv run python main.py          # host/port 来自 .env（HOST 固定 127.0.0.1）
```

骨架接口（契约 `docs/api/openapi.yaml` 0.1.0）：

- `GET /api/health` —— MySQL / MongoDB / Redis / Chroma 连通性 + Embedding
  生效模式；任一依赖不可用仍 200，`data.status = degraded`
- `GET /api/openapi.json` —— 契约原文的 JSON 序列化
- `GET /api/docs` —— Swagger UI（flask-swagger-ui，离线静态资源）

## Embedding 双模（云端优先、本地侧车兜底）

Embedding 端点有两种生效模式，`/api/health` 的 `data.embedding.mode` 如实上报：

| 场景 | mode | model | status | 整体 status |
| --- | --- | --- | --- | --- |
| 云端可用 | `cloud` | `EMBEDDING_MODEL` | `up` | `ok` |
| 云端不可用、本地侧车可用 | `local` | `EMBEDDING_LOCAL_MODEL` | `up` | `ok` |
| 都不可用（或本地被禁用） | `null` | `EMBEDDING_MODEL` | `down` | `degraded` |

判定顺序固定为 **cloud → local → down**：先探云端（5s 超时），失败且
`EMBEDDING_LOCAL_ENABLED=true` 时才探本地侧车；两者都失败仍 **HTTP 200**，
只让 `data.status = degraded`。云端失败必落 WARNING 日志（仅原因摘要，不含凭据）。

本地侧车是**独立 Python 3.10 进程**（torch/MPS 与后端运行时不同），位于仓库根
`tools/local_embedding/`，后端只经 HTTP（OpenAI 兼容）调用它：

```bash
# 仓库根执行（首次加载模型约 3s，默认监听 127.0.0.1:8010）
~/my/torch_python/.venv/bin/python tools/local_embedding/server.py
curl -s http://127.0.0.1:8010/health | python3 -m json.tool   # status=ok, dim=1024
```

后端 `.env` 对应三项（`.env.example` 已含模板）：

```dotenv
EMBEDDING_LOCAL_BASE_URL=http://127.0.0.1:8010/v1
EMBEDDING_LOCAL_MODEL=qwen3_embedding_0_6b
EMBEDDING_LOCAL_ENABLED=true
```

启动方式、API 细节、`input_type` 查询前缀、常见问题见
[`tools/local_embedding/README.md`](../tools/local_embedding/README.md)。

## 测试与 Lint

```bash
uv run ruff check .
uv run pytest
```

## 数据库迁移（flask-migrate / Alembic）

```bash
uv run flask --app main db upgrade              # 升级到最新版本
uv run flask --app main db current              # 查看当前版本
uv run flask --app main db revision -m "描述"   # 新增手写迁移
uv run flask --app main db revision --autogenerate -m "描述"  # 自动比对模型
```

说明：

- Alembic 版本表名带 `DB_TABLE_PREFIX` 前缀（如 `b0be-alembic_version`），
  业务表前缀经 `src/model.py` 的 `prefix()` 助手统一应用——worktree 之间
  共库不同前缀，互不干扰。
- `migrations/` 入 git；`flask db init` 仅首次 scaffolding 使用，勿重复执行。

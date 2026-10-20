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

## Embedding 三模式（默认纯本地，云端开关保留）

Embedding 端点的探测策略由 `EMBEDDING_MODE` 决定，**默认 `local`：只打本地
侧车，完全不碰云端**（零外发请求、零云端费用、零 5s 云端等待）。`/api/health`
的 `data.embedding.mode` 如实上报实际生效的一方：

| `EMBEDDING_MODE` | 探测顺序 | 成功时 mode / model | 失败时 mode / model |
| --- | --- | --- | --- |
| `local`（默认） | 只探本地侧车 | `local` / `EMBEDDING_LOCAL_MODEL` | `null` / `EMBEDDING_LOCAL_MODEL` |
| `cloud` | 只探云端 | `cloud` / `EMBEDDING_MODEL` | `null` / `EMBEDDING_MODEL` |
| `auto`（旧行为） | 云端 → 本地 → down | `cloud` 优先，云端失败则 `local` 兜底 | `null` / `EMBEDDING_MODEL` |

补充规则：

- `mode` 三态严格按契约映射：只有真正接管的一方才上报 `local` / `cloud`，
  不可用一律 `null`，`status=down`。契约（`docs/api/openapi.yaml`
  `EmbeddingHealth`）未改，枚举仍是 `cloud | local` 且 nullable。
- `local` 模式**无视** `EMBEDDING_LOCAL_ENABLED`（已显式选择本地，恒探测）；
  该开关只在 `auto` 模式下用于关闭兜底。
- `auto` 模式下云端配置不全（`EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` /
  `EMBEDDING_MODEL` 任一为空）时**直接跳过云端且不发请求**：
  `OpenAI(base_url="")` 会隐式回落到官方 `https://api.openai.com/v1`，若 key
  非空则凭据外泄。`cloud` 模式同样遵守这条安全短路。
- `EMBEDDING_MODE` 取值非法（如 `LOCALX`、空串）→ 回退 `local` 并落 WARNING，
  绝不会因笔误退回「先打云端」。
- 任一依赖不可用仍 **HTTP 200**，只让 `data.status = degraded`；失败必落
  WARNING 日志（仅原因摘要，不含凭据）。
- 本地侧车地址（`127.0.0.1` / `localhost` / `::1`）的探活**强制直连、绕过系统
  代理**：macOS 开着 Clash 等全局代理时，`httpx` 默认会把本机回环请求也发给
  代理，侧车停掉时代理返回 502 且耗时数秒，把纯本机探活变成对外依赖。云端
  地址不受影响，仍按系统代理设置出海。

**探活耗时（按模式分别表述）**：

| 模式 / 场景 | 典型耗时 | 最坏耗时 |
| --- | --- | --- |
| `local` + 侧车正常 | 数 ms ~ 数十 ms | 本地 15s 超时 |
| `local` + 侧车未起 | 立即失败（连接拒绝） | 本地 15s 超时 |
| `cloud` + 云端正常 | 数十 ms ~ 1s | 云端 5s 超时 |
| `auto` + 云端不可达、本地正常 | **5s +** 本地耗时 | 5s + 15s ≈ 20s |
| `auto` + 双不可达 | — | ≈ 20s |

也就是说：**默认 `local` 模式的 health 不再有那 5s 云端等待**，接口从「最坏
≈20s」降到「最坏 ≈15s、常态数十 ms」。健康检查调用方按所选模式设定超时：
`local` / `cloud` 可按 ≥15s，`auto` 才需要 ≥20s。

**切回云端**：只改一行 `.env` 即可（不需要改代码，也不需要重启之外的任何操作）：

```dotenv
EMBEDDING_MODE=auto    # 云端优先 + 本地兜底（推荐，最平滑）
# EMBEDDING_MODE=cloud # 只走云端，本地不参与
```

切回前确认 `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL`
三项已填（`cloud` 模式下缺项会直接 `mode=null/status=down`，不再兜底本地）。

本地侧车是**独立进程**（torch/MPS 与后端运行时不同），位于仓库根
`tools/local_embedding/`，后端只经 HTTP（OpenAI 兼容）调用它：

```bash
# 仓库根执行（首次加载模型约 3s，默认监听 127.0.0.1:8010）
~/my/torch_python/.venv/bin/python tools/local_embedding/server.py
curl -s http://127.0.0.1:8010/health | python3 -m json.tool
# → status=ok, dim=1024, device=mps, selftest=ok
```

侧车 `/health` 的 `selftest` 字段是启动时的**推理内核自检**结论
（`ok` / `failed` / `error` / `skipped`）。`failed` 表示该设备/精度的注意力内核
算出错误结果、向量不可信——此时后端探活仍会显示 `mode=local/status=up`
（HTTP 层确实通了），排障请以侧车 `/health` 与日志为准。

后端 `.env` 对应配置（`.env.example` 已含模板）：

```dotenv
EMBEDDING_MODE=local                                       # 默认：纯本地
EMBEDDING_LOCAL_BASE_URL=http://127.0.0.1:8010/v1
EMBEDDING_LOCAL_MODEL=qwen3_embedding_0_6b
EMBEDDING_LOCAL_ENABLED=true                              # 仅 auto 模式生效
# 以下三项仅 cloud / auto 模式读取，local 模式不读、不发请求
# EMBEDDING_BASE_URL=... / EMBEDDING_API_KEY=... / EMBEDDING_MODEL=...
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

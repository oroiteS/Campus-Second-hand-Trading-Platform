# 本地 Embedding 侧车（Qwen3-Embedding-0.6B）

把本机 `qwen3_embedding_0_6b/` 模型包装成一个 **OpenAI 兼容** 的
`POST /v1/embeddings` HTTP 服务，供 `campus_backend` 在云端 Embedding 不可用时
兜底（契约 `EmbeddingHealth.mode = local`）。

## 为什么独立成 `tools/local_embedding/`（而不是放进 `campus_backend/src/`）

| 维度 | Flask 后端 | 本侧车 |
| --- | --- | --- |
| 运行时 | Python **3.12**（`campus_backend/.venv`） | Python **3.10**（`~/my/torch_python/.venv`） |
| 依赖 | Flask / SQLAlchemy / openai…（**无 torch**） | torch 2.11（MPS）+ transformers + tokenizers + safetensors |
| 生命周期 | 随请求进程常驻 | 独立长驻进程，可单独重启/降级 |

torch 及推理栈与机器、芯片、CUDA/MPS 强相关，且**不允许**装进后端工程；两者
运行时完全不同，硬塞进 `campus_backend/src/` 会让后端被推理依赖绑架，也让
"后端只经 HTTP 调 Embedding" 的契约边界消失。故独立成平行目录，两者只经
HTTP（OpenAI 兼容协议）通信。

## 依赖（已装，无需再装）

```bash
~/my/torch_python/.venv/bin/python -c \
  "import torch, transformers, tokenizers, safetensors; print(transformers.__version__)"
```

侧车**只用标准库 `http.server`** 实现 HTTP 层，不引入 Flask —— 避免给 3.10
推理环境再加一层 Web 框架依赖。

## 启动

```bash
cd <仓库根>
~/my/torch_python/.venv/bin/python tools/local_embedding/server.py
# 默认监听 http://127.0.0.1:8010
```

常用参数 / 环境变量（**优先级：命令行 > 环境变量 > 默认值**）：

| 参数 | 环境变量 | 默认 | 说明 |
| --- | --- | --- | --- |
| `--host` | `LOCAL_EMBEDDING_HOST` | `127.0.0.1` | 监听地址（仅回环） |
| `--port` | `LOCAL_EMBEDDING_PORT` | `8010` | 端口（避开后端 5000/5010/5020/5030 与前端端口） |
| `--model-dir` | `LOCAL_EMBEDDING_MODEL_DIR` | 自动探测 | 模型目录；探测顺序：检出根平级 → 主仓根 → `~/qwen3_embedding_0_6b` |
| `--device` | `LOCAL_EMBEDDING_DEVICE` | `auto` | `auto` / `cpu` / `mps` |
| `--batch-size` | `LOCAL_EMBEDDING_BATCH_SIZE` | `32` | 单批条数 |
| `--max-length` | `LOCAL_EMBEDDING_MAX_LENGTH` | `512` | 截断长度（token） |
| `--log-level` | `LOCAL_EMBEDDING_LOG_LEVEL` | `INFO` | 日志级别 |

> **worktree 注意**：模型目录被根 `.gitignore` 忽略，worktree 检出里没有它。
> 侧车会自动回退到主仓根目录的 `qwen3_embedding_0_6b/`，无需手动指定。
> 若放在别处，用 `--model-dir /abs/path` 或 `LOCAL_EMBEDDING_MODEL_DIR` 指定。

## API

### `GET /health`

```json
{
  "status": "ok",
  "model": "qwen3_embedding_0_6b",
  "dim": 1024,
  "device": "mps",
  "model_path": "/…/qwen3_embedding_0_6b",
  "backend": "transformers",
  "load_seconds": 2.94,
  "loaded_at": "2026-10-20T16:16:15+0800"
}
```

模型加载失败时返回 **HTTP 503**，`status = "error"` 且带结构化 `error`
（`type` / `message` / `model_path`）；进程不退出，便于排障后重启。

### `POST /v1/embeddings`（OpenAI 兼容）

请求：

```json
{
  "input": ["罗技机械键盘 九成新", "苹果笔记本"],
  "model": "qwen3_embedding_0_6b",
  "dimensions": 1024,
  "input_type": "document"
}
```

- `input`：**字符串** 或 **字符串数组**（OpenAI 语义；数组为空 / 含非字符串 / 含空白文本一律 400）。
- `model`：仅回显用途，不参与路由（单模型服务）。
- `dimensions`：可选，只接受 `1024`（本模型原生维度，不做 Matryoshka 截断，保证与 Chroma 集合一致）。
- `input_type`：**非标准扩展字段**，`"query"` | `"document"`（默认）。见下节。

响应：

```json
{
  "object": "list",
  "data": [
    {"object": "embedding", "index": 0, "embedding": [0.047676, -0.015516, "… 共 1024 维 …"]}
  ],
  "model": "qwen3_embedding_0_6b",
  "usage": {"prompt_tokens": 47, "total_tokens": 47}
}
```

错误体沿用 OpenAI 风格 `{"error": {"message", "type", "param", "code"}}`：
`400` 请求非法、`503` 模型未就绪、`500` 推理异常、`404`/`405` 路径或方法不符。

### 查询 / 文档非对称前缀（`input_type`）

Qwen3-Embedding 对**查询**建议加指令前缀（取自模型
`config_sentence_transformers.json` 的 `prompts.query`）：

```
Instruct: Given a web search query, retrieve relevant passages that answer the query
Query:
```

- `input_type="document"`（默认）：不加前缀，用于商品标题/描述入库；
- `input_type="query"`：加上述前缀，用于检索查询。

OpenAI SDK 通过 `extra_body` 传入，**不破坏兼容性**（不支持该字段的客户端
不加即可，等价于 `document`）：

```python
client = OpenAI(base_url="http://127.0.0.1:8010/v1", api_key="local")
client.embeddings.create(
    input=["想买个便宜的机械键盘"],
    model="qwen3_embedding_0_6b",
    extra_body={"input_type": "query"},
)
```

## 与后端的关系

```text
campus_backend (Py3.12, 无 torch)
  └─ GET /api/health → services/system_service._embedding_health
       ├─ 1) 云端 EMBEDDING_BASE_URL（5s 超时）→ 可用则 mode=cloud
       └─ 2) 云端失败且 EMBEDDING_LOCAL_ENABLED → 本侧车
              EMBEDDING_LOCAL_BASE_URL（默认 http://127.0.0.1:8010/v1）
              → 可用则 mode=local；否则 mode=null / status=down
```

后端 `.env`（`campus_backend/.env.example` 有模板）：

```dotenv
EMBEDDING_LOCAL_BASE_URL=http://127.0.0.1:8010/v1
EMBEDDING_LOCAL_MODEL=qwen3_embedding_0_6b
EMBEDDING_LOCAL_ENABLED=true
```

后端**只经 HTTP** 调用本侧车，不 import torch、不加载模型；停止侧车后
`/api/health` 仍返回 **HTTP 200**，仅 `data.status = degraded`、
`data.embedding.mode = null`。

## 实现关键点

- **设备**：`auto` → MPS 可用则 `mps + bfloat16`，否则 `cpu + float32`。
- **池化**：模型是 `pooling_mode_lasttoken: true`（不是 CLS、不是 mean）。取
  **最后一个有效 token** 的 hidden state —— 用 `attention_mask.sum(dim=1) - 1`
  定位，而非 `hidden[:, -1]`（后者在 padding 情况下会取到 pad）。
- **padding**：`padding_side = "right"`，与 last-token 定位方式配套（left padding
  下"最后一个有效 token"仍在末尾，但批内下标语义更易错，统一选 right）。
- **归一化**：等价 `sentence_transformers` 的 `Normalize` 模块，L2 后范数 ≈ 1.0。
- **维度**：加载时校验 `config.hidden_size == 1024`，推理时再断言每行 1024。
- **并发**：MPS 上并发推理会争抢命令队列，`embed()` 内部加锁串行化；
  HTTP 层是 `ThreadingHTTPServer`，探活与推理不会互相堵死。
- **离线**：`local_files_only=True` + `trust_remote_code=False`，不联网、不执行模型侧代码。

## 自测

```bash
cd tools/local_embedding
~/my/torch_python/.venv/bin/python test_server.py
```

三层：协议层（假 embedder，无需模型）→ 模型层（真模型，1024 维 / 范数 / 批一致 /
语义近似 / query 前缀）→ 端到端（真模型 + 真实 HTTP）。缺依赖时打印 SKIP 并以
退出码 0 结束（不算失败），断言失败退出码 1。

## 常见问题

**1. `ModuleNotFoundError: No module named 'transformers'`**
跑错解释器了。必须用 `~/my/torch_python/.venv/bin/python`，不是
`campus_backend/.venv/bin/python`（3.12，没有 torch）。

**2. 启动日志出现 `可选依赖 scipy 导入失败 … 已在进程内标记为不可用`**
本机 `scipy 1.15.3` 的 `_propack` 动态库损坏（`dlopen … has a zero-fill section
type`），`sklearn` 随之导入失败；而 `transformers 5.20.2` 在**模块导入期**无条件
`from sklearn.metrics import roc_curve` / `from scipy.optimize import …`，会把整个
`import transformers` 拖挂。侧车启动时探测这两个包，导入失败就在
`sys.modules` 里置 `None`（`transformers` 的 `is_*_available()` 用
`importlib.util.find_spec` 判断，见 `server.py::_disable_broken_optional_deps`）。
推理不需要 scipy/sklearn，屏蔽无副作用；包修好后该逻辑自动变成 no-op。

**3. `/health` 返回 503**
看 `error.message`：`FileNotFoundError` = 模型目录不对（用 `--model-dir` 指定）；
`ImportError` = 依赖缺失；内存不足会看到 `RuntimeError / MPS backend out of memory`。
`--device cpu` 可绕过 MPS 相关问题排查。

**4. 首次请求慢 / 冷启动**
模型加载约 3s（MPS）。建议先 `curl /health` 预热再压测；稳态单条中文短文本
约 20–60ms。

**5. 端口 8010 被占用**
`--port 8011` 并同步改后端 `EMBEDDING_LOCAL_BASE_URL`。

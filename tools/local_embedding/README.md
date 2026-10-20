# 本地 Embedding 侧车（Qwen3-Embedding-0.6B）

把本机 `qwen3_embedding_0_6b/` 模型包装成一个 **OpenAI 兼容** 的
`POST /v1/embeddings` HTTP 服务，供 `campus_backend` 调用（契约
`EmbeddingHealth.mode = local`）。后端**默认 `EMBEDDING_MODE=local`：只打本侧车、
不发任何云端请求**；云端仅作为 `EMBEDDING_MODE=cloud|auto` 时的可选路径保留。

## 为什么独立成 `tools/local_embedding/`（而不是放进 `campus_backend/src/`）

| 维度 | Flask 后端 | 本侧车 |
| --- | --- | --- |
| 运行时 | Python **3.12**（`campus_backend/.venv`） | 独立 venv `~/my/torch_python/.venv` |
| 依赖 | Flask / SQLAlchemy / openai…（**无 torch**） | torch 2.14（MPS）+ transformers 5.20 + tokenizers + safetensors |
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

侧车**只用标准库 `http.server`** 实现 HTTP 层，不引入 Flask —— 避免给推理
环境再加一层 Web 框架依赖。侧车代码只用 Py3.10+ 语法，可在 3.10 / 3.12 下运行。

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
  "dtype": "bfloat16",
  "model_path": "/…/qwen3_embedding_0_6b",
  "backend": "transformers",
  "selftest": "ok",
  "selftest_detail": {
    "status": "ok",
    "seq_lens": [17, 24, 32],
    "head_dim": 128,
    "device": "mps",
    "dtype": "bfloat16",
    "max_rel_err": 0.004573,
    "per_seq": [{"seq_len": 17, "rel_err": 0.00381}, "…"],
    "threshold": 0.05,
    "elapsed_ms": 56.0
  },
  "load_seconds": 2.94,
  "loaded_at": "2026-10-20T16:16:15+0800"
}
```

- `selftest`：启动时**推理内核自检**的结论，`ok` / `failed` / `error` / `skipped`；
  见下文「运行时内核自检」。`failed` 时 `/health` 仍返回 200（服务可跑但结果可疑），
  同时打 ERROR 日志——不会出现“探活永远正常、向量其实全错”。
- 模型加载失败时返回 **HTTP 503**，`status = "error"` 且带结构化 `error`
  （`type` / `message` / `model_path`）；进程不退出，便于排障后重启。

### `GET /v1/models`（OpenAI 兼容）

```json
{
  "object": "list",
  "data": [
    {"id": "qwen3_embedding_0_6b", "object": "model", "created": 0, "owned_by": "local"}
  ]
}
```

OpenAI 官方 SDK、LangChain 等客户端常先探测该接口；`POST /v1/models` 返回
405（语义与 `GET` 明确区分）。

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
`400` 请求非法（`type=invalid_request_error`）、`503` 模型未就绪
（`type=service_unavailable`）、`500` 推理异常（`type=server_error`）、
`404` / `405` 路径或方法不符。

> 所有**非 200** 响应都会带上 `Connection: close` 并主动断开连接：错误分支
> 通常没有消费请求体，若在 keep-alive 上复用，残留 body 会被当作下一个请求行，
> 造成 400/501 串包。正常 200 响应仍保持 keep-alive 复用。

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
       EMBEDDING_MODE=local（默认，推荐）
         └─ 只探本侧车 EMBEDDING_LOCAL_BASE_URL（默认 http://127.0.0.1:8010/v1）
              → 可用则 mode=local；否则 mode=null / status=down
            （不读云端配置、不发云端请求、无 5s 云端等待）
       EMBEDDING_MODE=auto（旧行为）
         ├─ 1) 云端 EMBEDDING_BASE_URL（5s 超时）→ 可用则 mode=cloud
         └─ 2) 云端失败且 EMBEDDING_LOCAL_ENABLED → 本侧车 → mode=local
       EMBEDDING_MODE=cloud
         └─ 只探云端；失败即 mode=null（不回落本侧车）
```

后端 `.env`（`campus_backend/.env.example` 有模板）：

```dotenv
EMBEDDING_MODE=local                                     # 默认；只打本侧车
EMBEDDING_LOCAL_BASE_URL=http://127.0.0.1:8010/v1
EMBEDDING_LOCAL_MODEL=qwen3_embedding_0_6b
EMBEDDING_LOCAL_ENABLED=true                             # 仅 auto 模式用于开关兜底
```

后端**只经 HTTP** 调用本侧车，不 import torch、不加载模型；停止侧车后
`/api/health` 仍返回 **HTTP 200**，仅 `data.status = degraded`、
`data.embedding.mode = null`。

### 探活耗时（P3-1）

耗时取决于 `EMBEDDING_MODE`：

| 模式 / 场景 | 大致耗时 | 说明 |
| --- | --- | --- |
| **`local`（默认）+ 本侧车正常** | **数 ms – 数十 ms** | 只探本侧车，**没有 5s 云端等待** |
| `local` + 本侧车未启动 | 立即失败 | 连接拒绝，仍 HTTP 200 + `degraded` |
| `local` + 本侧车挂死 | ≤15s | 本地探活超时 |
| `auto` + 云端正常 | 数十 ms – 1s | 只打云端，不碰本地 |
| `auto` + 云端不可达 | **≈5s + 本地耗时** | 云端 5s 超时**之后**才探本侧车 |
| `auto` + 云端 5xx 秒回 | < 1s + 本地耗时 | 立即降级探本地 |
| `auto` + 云端与本地都不通 | ≈20s | 5s + 本地 15s 超时 |
| `cloud` + 云端不可达 | ≈5s | 只探云端，不回落本地 |

默认 `local` 模式下 `/api/health` 不再有那 5s 停顿。后端探活**回环 / 本机地址**
（`127.0.0.0/8`、`localhost`、`::1`、`::ffff:127.0.0.1`、`0.0.0.0`）时**强制直连、
绕过系统代理**，所以本机开着 Clash 等全局代理也不影响本侧车的探活结论与耗时。
⚠️ 若把侧车改配到**非回环地址**（`172.x` / docker 服务名 / `host.docker.internal`），
该保护不生效，请求会重新走系统代理（退化成 502 + 秒级耗时），详见后端 README 的适用边界。只有在 `auto` 模式下
（云端优先顺序决定）才会出现「云端地址不可达 → health 慢约 5 秒」；此时前端/
联调请按 ≥20s 设超时。

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

## 运行时内核自检（防“探活正常、向量全错”）

启动加载模型后立刻跑一次 `run_kernel_selftest()`，结论写入 `/health.selftest`：

- **输入**：固定种子（20261020）生成 Q/K/V，`seq_len ∈ {17, 24, 32}`
  （覆盖 MPS SDPA 的长序列分支 —— 历史 bug 正是在 seq>16 触发），
  `head_dim = 128`（与真实模型一致）、`heads = 4`；
- **被测**：生产配置（`mps + bfloat16` 或 `cpu + float32`）上的
  `F.scaled_dot_product_attention(..., is_causal=True)`；
- **基准**：**独立实现**——`matmul + 显式 tril mask + softmax + matmul` 手算
  causal attention（不能用 SDPA 当基准，否则内核坏了两边一起错、差值为 0）；
- **判据**：相对误差 `max|diff| / max|baseline| ≤ 0.05`；正常 bf16 实测
  ≈0.0025–0.0046，坏内核可达 1e+0；
- **失败行为**：`/health` 报 `selftest: "failed"` + ERROR 日志，**但不阻止启动**
  （仍可 `--device cpu` 兜底排查）。

> 注：`head_dim` 必须取真实值。实测 torch 2.14.1 的 MPS bf16 SDPA 在
> `head_dim ∈ {8, 16}` 且 `seq > 16` 时**仍然**给出错误结果（rel_err≈1.18），
> 而 `head_dim ∈ {32, 64, 128, 256}` 正常。Qwen3-Embedding-0.6B 是 128，
> 因此用真实 head_dim 自检，既覆盖长序列路径、又不会把无关缺口误报成生产故障。

## 自测

```bash
cd tools/local_embedding
~/my/torch_python/.venv/bin/python test_server.py
```

四层，共 100+ 项断言：

1. **协议层**（假 embedder，无需 torch）：`/health`、`/v1/models`、
   `/v1/embeddings` 的字段/错误码/OpenAI 结构；**keep-alive 串包回归**
   （404/405/400 之后同连接必须断开，200 之后必须复用）。
2. **内核自检层**：生产配置必须 `ok`、CPU fp32 必须 rel_err=0；再用代理 shim
   把 SDPA 换成“输出全零”的坏内核，验证自检确实能报 `failed`。
3. **模型层**：三方一致性（单条 / 等长批量无 padding / 混合批量有 padding，
   两两 cosine ≥ 0.99）、长度覆盖 **17 / 24 / 32 token**、query 前缀
   **文本层断言**（见下）、跨设备/精度对照、独立参考实现对照、检索排序。
4. **端到端**：真模型 + 真 HTTP，含 `/v1/models` 与 keep-alive 复用。

缺依赖时打印 SKIP 并以退出码 0 结束（不算失败），断言失败退出码 1。

### 三种「对照」的分工（别混淆）

不同手段能抓的缺陷类别不同，测试文件里刻意分开并注明：

| 手段 | 对照对象 | 能抓的缺陷 | 抓不到的 |
| --- | --- | --- | --- |
| **CPU fp32 对照** | 同一个 `LocalEmbedder` 实现，只切 `device`/`dtype` | 设备/精度相关的**内核 bug**（如 MPS bf16 SDPA 算错） | 池化索引、归一化方向等**算法逻辑错误**（两边一起错，差异恒为 0） |
| **独立参考实现对照**（模型层） | 手写 `forward → mask 末位 → L2`，不复用 `_run_batches` | 池化取错位置、漏归一化、`hidden[:,-1]` 取到 pad 等**算法错误** | 设备内核问题（两者同设备） |
| **手算注意力基准**（内核自检） | `matmul + tril mask + softmax`，不走 SDPA | attention **内核/算法**错误 | 池化与 embedding 层逻辑 |

### query 前缀的文本层断言

只看「query≠document 向量」「前缀 27 token」这类**结果层**观察是不够的：
把前缀换成另一个短错串、拼到文本**之后**、或把 query/document 前缀**互换**，
都能让向量"不同且够长"，结果层断言照样全绿。因此测试会 **spy
`_run_batches` 的入参**，在**文本层**逐字断言：

```python
prepared[0] == embedder.query_prefix + text  # 内容与位置都精确
prepared[0].startswith(embedder.query_prefix)  # 前缀在前
not prepared[0].endswith(embedder.query_prefix)  # 排除后置拼接
prepared[0].count(embedder.query_prefix) == 1  # 只出现一次
not doc_prepared[0].startswith(embedder.query_prefix)  # document 不带 query 前缀
```

外加两条更强的约束：

- `embedder.query_prefix` 必须与模型 `config_sentence_transformers.json` 的
  `prompts.query` **逐字一致**（排除换成短错串）；
- **哨兵测试**：临时把两个前缀替换为 `[[Q-SENTINEL]]` / `[[D-SENTINEL]]`，
  验证 query 路径取前者、document 路径取后者、二者未互换，最后复原
  （真实配置里 `prompts.document` 恰为空，不做哨兵就漏掉"document 也用了
  query 前缀"这类错误）。

## 常见问题

**1. `ModuleNotFoundError: No module named 'transformers'`**
跑错解释器了。必须用 `~/my/torch_python/.venv/bin/python`，不是
`campus_backend/.venv/bin/python`（3.12，没有 torch）。

**2. 启动日志出现「可选依赖 sklearn/scipy 存在但不可用 … 已在进程内标记为不可用」**
`transformers` 5.20.x 在**模块导入期**就执行 `from sklearn.metrics import roc_curve`
（候选生成器）与 `from scipy.optimize import linear_sum_assignment`（目标检测损失），
两处都由 `is_*_available()` 守卫；该守卫走 `importlib.util.find_spec`，所以只要
包装上了但**导入即失败**（历史环境：`scipy 1.15.3` 的 `_propack` 动态库损坏，
`sklearn` 随之失败），`import transformers` 就会崩。

侧车在 `transformers` 导入前调用 `_shield_broken_optional_deps()`：
**按 transformers 真正需要的那一句 import 探测**（`sklearn.metrics.roc_curve` /
`scipy.optimize.linear_sum_assignment`），只在确实失败时把**该包**在
`sys.modules` 置 `None`。粒度是最小化的——不会因为 `scipy.linalg` 之类别的子模块
坏掉就整包屏蔽 scipy；两个包各自独立判断；**未安装**时不做任何处理
（`find_spec` 本来就是 `None`）。侧车推理不需要这两个包，包修好后自动 no-op。

**2b. `/health` 里 `selftest: "failed"`**
说明该设备/精度的注意力内核算错了，向量不可信。先 `--device cpu` 复测：
CPU 也失败 → 代码/依赖问题；仅 MPS 失败 → torch/MPS 内核问题，降级用 CPU
或换 torch 版本。

**3. `/health` 返回 503**
看 `error.message`：`FileNotFoundError` = 模型目录不对（用 `--model-dir` 指定）；
`ImportError` = 依赖缺失；内存不足会看到 `RuntimeError / MPS backend out of memory`。
`--device cpu` 可绕过 MPS 相关问题排查。

**4. 首次请求慢 / 冷启动**
模型加载约 3s（MPS）。建议先 `curl /health` 预热再压测；稳态单条中文短文本
约 20–60ms。

**5. 端口 8010 被占用**
`--port 8011` 并同步改后端 `EMBEDDING_LOCAL_BASE_URL`。

"""本地 Embedding 侧车自测脚本（不依赖 pytest，缺失依赖时打印 SKIP 并以 0 退出）。

用法::

    ~/my/torch_python/.venv/bin/python test_server.py

分四层：

1. **协议层（无依赖）**：用假 embedder（FakeEmbedder）起真实 HTTP 服务，
   校验 /health、/v1/models、/v1/embeddings 的请求解析、错误码、OpenAI 响应
   结构，以及 **keep-alive 不复用脏连接**（P2-1 回归用例）。这一层即使没装
   torch/transformers 也会完整执行。
2. **内核自检层（需 torch）**：验证 ``run_kernel_selftest`` 在正常内核上通过、
   在错误内核上能报 ``failed``（用 shim 模拟坏内核），防“探活正常、向量全错”。
3. **模型层（需 torch + transformers + 本地模型）**：
   - 单条 / 等长批量（无 padding）/ 混合批量（有 padding）**三方一致性**；
   - 长度覆盖 **≥17 / ≥24 / ≥32 token**（历史 MPS SDPA bug 的触发区间）；
   - query 前缀路径（27 token，必然走长序列）+ **文本层**前缀断言
     （spy 送入模型的文本：前缀内容逐字、位置在前、query/document 归属）；
   - **同实现跨设备/精度对照**（MPS vs CPU fp32，防设备相关内核 bug）与
     **独立参考实现对照**（手写 last-token + L2，防池化/归一化算法错误）；
   - 中文语义近似度与检索排序。
4. **端到端**：真模型 + 真实 HTTP 往返（含 keep-alive 与 /v1/models）。

任何一层缺依赖 → 打印 SKIP 继续，最终退出码 0；断言失败退出码 1。
"""

from __future__ import annotations

import json
import math
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server as sidecar  # noqa: E402 —— 同目录导入

PASSED: list[str] = []
SKIPPED: list[str] = []
FAILED: list[str] = []

# 三方一致性阈值：单条 / 等长批量 / 混合批量 两两 cosine 下限
CONSISTENCY_MIN_COS = 0.99
# 跨设备/跨精度对照阈值（MPS 结果 vs 同实现 CPU fp32 结果）
BASELINE_MIN_COS = 0.99

# 商品标题风格的中文语料（长度覆盖用；真实商品数据长得就是这些样子）
SEEDS = {
    "keyboard": "罗技机械键盘 九成新 青轴 宿舍自提 可小刀 配件齐全 无明显磨损 有意者私聊",
    "laptop": "苹果笔记本 MacBook Air M2 芯片 十六 G 内存 五百一十二 G 固态 深空灰 电池健康",
    "card": "食堂饭卡 余额五十元 可直接刷卡 毕业离校转让 教学楼当面交易 有意者请联系",
    "book": "微积分教材 同济版 第七版 上下册 笔记齐全 无破损 考研复习必备 低价出",
}


# --------------------------------------------------------------------------
# 断言框架
# --------------------------------------------------------------------------


def check(name: str, condition: bool, detail: str = "") -> bool:
    if condition:
        PASSED.append(name)
        print(f"  ✓ {name}")
        return True
    FAILED.append(f"{name} {detail}".strip())
    print(f"  ✗ {name} {detail}")
    return False


def skip(name: str, reason: str) -> None:
    SKIPPED.append(f"{name}（{reason}）")
    print(f"  - SKIP {name}：{reason}")


# --------------------------------------------------------------------------
# 假 embedder（协议层用，无任何模型依赖）
# --------------------------------------------------------------------------


class FakeEmbedder:
    """确定性替身：向量由文本哈希生成，便于断言结构与归一化行为。"""

    def __init__(self, *, ready: bool = True, dim: int = sidecar.EMBEDDING_DIM):
        self.model_name = "fake-embedding"
        self.dim = dim
        self.device = "cpu"
        self.dtype_name = "float32"
        self._ready = ready
        self.selftest = {"status": "ok", "max_rel_err": 0.001, "threshold": 0.05}
        self.error = (
            None
            if ready
            else {"type": "FileNotFoundError", "message": "模型目录不存在", "model_path": "/nope"}
        )
        self.seen: list[tuple[list[str], str]] = []

    @property
    def ready(self) -> bool:
        return self._ready

    def health(self) -> dict:
        body = {
            "status": "ok" if self._ready else "error",
            "model": self.model_name,
            "dim": self.dim,
            "device": self.device,
            "model_path": "/fake",
            "backend": "fake",
            "selftest": self.selftest["status"] if self._ready else "skipped",
        }
        if self._ready:
            body["dtype"] = self.dtype_name
            body["selftest_detail"] = self.selftest
        else:
            body["error"] = self.error
        return body

    def models(self) -> dict:
        return {
            "object": "list",
            "data": [{"id": self.model_name, "object": "model", "created": 0, "owned_by": "local"}],
        }

    def embed(self, texts: list[str], input_type: str = "document") -> sidecar.EmbeddingResult:
        if not self._ready:
            raise sidecar.EmbeddingUnavailable("模型未就绪：FileNotFoundError: 模型目录不存在")
        self.seen.append((texts, input_type))
        vectors: list[list[float]] = []
        for text in texts:
            seed = sum(ord(char) for char in text) % 97
            raw = [((seed + index) % 13) - 6.0 for index in range(self.dim)]
            norm = math.sqrt(sum(value * value for value in raw)) or 1.0
            vectors.append([value / norm for value in raw])
        return sidecar.EmbeddingResult(
            vectors=vectors, prompt_tokens=sum(len(text) for text in texts)
        )


# --------------------------------------------------------------------------
# 起停 HTTP 服务
# --------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class Sidecar:
    """在后台线程运行 EmbeddingHTTPServer 的上下文管理器。"""

    def __init__(self, embedder):
        self.embedder = embedder
        self.server = sidecar.EmbeddingHTTPServer(("127.0.0.1", _free_port()), embedder)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> Sidecar:
        self.thread.start()
        _wait_ready(self.port)
        return self

    def __exit__(self, *_exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _wait_ready(port: int, timeout_s: float = 5.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.02)
    raise TimeoutError(f"侧车端口 {port} 未在 {timeout_s}s 内就绪")


def request(
    base: str, path: str, *, method: str = "GET", payload: dict | None = None
) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def raw_keepalive_probe(port: int, first_request: bytes, second_request: bytes) -> list[bytes]:
    """在同一 TCP 连接上连发两个请求，返回每次读到的原始响应（用于串包检测）。"""
    received: list[bytes] = []
    with socket.create_connection(("127.0.0.1", port), timeout=5) as conn:
        conn.sendall(first_request)
        time.sleep(0.25)
        try:
            received.append(conn.recv(65536))
        except OSError:  # 对端已关连接（预期行为）
            received.append(b"")
        try:
            conn.sendall(second_request)
            time.sleep(0.25)
            received.append(conn.recv(65536))
        except OSError:
            received.append(b"")
    return received


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


def l2_norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


# --------------------------------------------------------------------------
# 第 1 层：协议层
# --------------------------------------------------------------------------


def _post_request(path: str, body: bytes) -> bytes:
    head = (
        f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
    ).encode()
    return head + body


def test_protocol() -> None:
    print("\n[1/4] 协议层（假 embedder，无需模型）")

    with Sidecar(FakeEmbedder()) as car:
        status, body = request(car.base, "/health")
        check("GET /health 返回 200", status == 200, f"实际 {status}")
        check("health.status == ok", body.get("status") == "ok", str(body))
        check("health.dim == 1024", body.get("dim") == 1024, str(body.get("dim")))
        check("health 含 selftest 字段", "selftest" in body, str(body.keys()))
        check("health.selftest == ok", body.get("selftest") == "ok", str(body.get("selftest")))

        # GET /v1/models（P2-2：OpenAI 语义，客户端/LangChain 会探测）
        status, body = request(car.base, "/v1/models")
        check("GET /v1/models 返回 200", status == 200, f"实际 {status}")
        check("models.object == list", body.get("object") == "list", str(body.get("object")))
        entries = body.get("data", [])
        check("models.data 非空", bool(entries), str(entries))
        if entries:
            first_model = entries[0]
            check(
                "models.data[i] 结构 {id,object,created,owned_by}",
                {"id", "object", "created", "owned_by"} <= set(first_model),
                str(set(first_model)),
            )
            check("models.data[i].object == model", first_model.get("object") == "model")
            check(
                "models 含服务自身模型名",
                first_model.get("id") == car.embedder.model_name,
                str(first_model.get("id")),
            )

        status, body = request(
            car.base, "/v1/embeddings", method="POST", payload={"input": ["文本一", "文本二"]}
        )
        check("POST /v1/embeddings 返回 200", status == 200, f"实际 {status}")
        check("响应 object == list", body.get("object") == "list", str(body.get("object")))
        check("data 长度 == 2", len(body.get("data", [])) == 2, str(body.get("data")))
        first = body["data"][0]
        check(
            "data[i] 结构 {object,index,embedding}",
            set(first) == {"object", "index", "embedding"},
            str(set(first)),
        )
        check("index 递增", [item["index"] for item in body["data"]] == [0, 1])
        check("向量维度 1024", len(first["embedding"]) == 1024, str(len(first["embedding"])))
        check(
            "usage.prompt_tokens/total_tokens 存在",
            set(body.get("usage", {})) == {"prompt_tokens", "total_tokens"},
            str(body.get("usage")),
        )

        # input 为单个字符串（OpenAI 语义）
        status, body = request(
            car.base, "/v1/embeddings", method="POST", payload={"input": "单个文本"}
        )
        check("input 为字符串时返回 1 条", status == 200 and len(body["data"]) == 1, str(status))

        # input_type 透传（query / document）
        car.embedder.seen.clear()
        status, _ = request(
            car.base,
            "/v1/embeddings",
            method="POST",
            payload={"input": ["键盘"], "input_type": "query"},
        )
        check(
            "input_type=query 透传到 embed",
            status == 200 and car.embedder.seen[-1][1] == "query",
            str(car.embedder.seen[-1:]),
        )
        request(car.base, "/v1/embeddings", method="POST", payload={"input": ["键盘"]})
        check("input_type 默认 document", car.embedder.seen[-1][1] == "document")

        # 非法请求一律 400 + OpenAI 风格 error
        cases = [
            ("input 缺失", {}),
            ("input 空数组", {"input": []}),
            ("input 元素非字符串", {"input": [123]}),
            ("input 空白文本", {"input": ["   "]}),
            ("input_type 非法", {"input": ["x"], "input_type": "other"}),
            ("dimensions 非 1024", {"input": ["x"], "dimensions": 512}),
        ]
        for name, payload in cases:
            status, body = request(car.base, "/v1/embeddings", method="POST", payload=payload)
            ok = status == 400 and body.get("error", {}).get("message")
            check(f"{name} → 400 + error.message", bool(ok), f"实际 {status} {body}")

        status, body = request(car.base, "/v1/embeddings", method="POST", payload={"input": ["x"]})
        check("合法请求在 400 用例之后仍可用", status == 200)

        status, body = request(car.base, "/v1/embeddings")
        check("GET /v1/embeddings → 405", status == 405, f"实际 {status}")
        status, body = request(car.base, "/v1/models", method="POST", payload={"x": 1})
        check("POST /v1/models → 405", status == 405, f"实际 {status}")
        status, body = request(car.base, "/health", method="POST", payload={"x": 1})
        check("POST /health → 405", status == 405, f"实际 {status}")
        status, body = request(car.base, "/no-such")
        check("未知路径 → 404", status == 404, f"实际 {status}")

        # ---- P2-1 keep-alive 串包回归 ----
        # 非 200 分支不消费请求体：若不主动关连接，残留 body 会被当成下一个
        # 请求行，第二次请求拿到 400/501 HTML。
        bad_404 = _post_request("/v1/nope", b'{"input":["x"]}')
        good_get = b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
        first, second = raw_keepalive_probe(car.port, bad_404, good_get)
        check(
            "POST 未知路径 → 404 且响应体是 JSON error",
            first.startswith(b"HTTP/1.1 404") and b'"error"' in first,
            first[:80].decode(errors="replace"),
        )
        check(
            "404 后同连接不再串包（服务端主动关闭）",
            second == b"",
            f"收到 {second[:120]!r}",
        )

        bad_405 = _post_request("/v1/models", b'{"x":1}')
        first, second = raw_keepalive_probe(car.port, bad_405, good_get)
        check(
            "POST /v1/models → 405 后同连接不串包",
            first.startswith(b"HTTP/1.1 405") and second == b"",
            f"{first[:40]!r} / {second[:120]!r}",
        )

        bad_body = _post_request("/v1/embeddings", b"not-json")
        first, second = raw_keepalive_probe(car.port, bad_body, good_get)
        check(
            "非法 JSON 400 后同连接不串包",
            first.startswith(b"HTTP/1.1 400") and second == b"",
            f"{first[:40]!r} / {second[:120]!r}",
        )

    # 模型未就绪：/health 503，embeddings 503，进程不崩
    with Sidecar(FakeEmbedder(ready=False)) as car:
        status, body = request(car.base, "/health")
        check("模型未就绪 /health 返回 503", status == 503, f"实际 {status}")
        check("503 响应带结构化 error", isinstance(body.get("error"), dict), str(body))
        check("未就绪时 selftest == skipped", body.get("selftest") == "skipped", str(body))
        status, body = request(car.base, "/v1/embeddings", method="POST", payload={"input": ["x"]})
        check("模型未就绪 /v1/embeddings 返回 503", status == 503, f"实际 {status}")
        check(
            "未就绪 503 的 error.type 为 service_unavailable",
            body.get("error", {}).get("type") == "service_unavailable",
            str(body.get("error")),
        )

    # 真实 LocalEmbedder：模型目录不存在时 load() 返回 False 而非抛异常
    broken = sidecar.LocalEmbedder("/nonexistent/qwen3_embedding_0_6b")
    loaded = broken.load()
    check("坏模型路径 load() 返回 False（进程不崩）", loaded is False, str(loaded))
    broken_health = broken.health()
    check(
        "坏模型路径 health.status == error", broken_health["status"] == "error", str(broken_health)
    )
    check(
        "坏模型路径 error.type == FileNotFoundError",
        broken_health["error"]["type"] == "FileNotFoundError",
        str(broken_health["error"]),
    )
    check("坏模型路径 dim 仍如实上报 1024", broken_health["dim"] == 1024, str(broken_health["dim"]))


# --------------------------------------------------------------------------
# 第 2 层：推理内核自检
# --------------------------------------------------------------------------


def _load_torch():
    """探测 torch；缺失返回 None（调用方打印 SKIP）。"""
    try:
        sidecar._shield_broken_optional_deps()
        import torch
    except Exception as exc:  # noqa: BLE001 —— 缺依赖一律 SKIP
        print(f"  依赖不可用：{type(exc).__name__}: {exc}")
        return None
    return torch


class _BrokenSdpaFunctional:
    """代理真实 ``torch.nn.functional``，只把 SDPA 换成“输出全零”的坏内核。

    其余算子（matmul / softmax / tril …）保持真实，因此自检的独立基准仍然
    正确、被测内核却是坏的——这正是要验证的失败分支。
    """

    def __init__(self, real_functional, real_torch):
        self.__dict__["_real"] = real_functional
        self.__dict__["_torch"] = real_torch

    def __getattr__(self, name):
        return getattr(self._real, name)

    def scaled_dot_product_attention(self, q, k, v, is_causal=False, **kwargs):  # noqa: ARG002
        return self._torch.zeros_like(q)


class _BrokenTorchShim:
    """代理真实 torch，仅 SDPA 坏掉；用于验证自检能报 ``failed``。"""

    def __init__(self, real_torch):
        self.__dict__["_real"] = real_torch
        self.__dict__["nn"] = type(
            "nn",
            (),
            {"functional": _BrokenSdpaFunctional(real_torch.nn.functional, real_torch)},
        )()

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_kernel_selftest() -> None:
    print("\n[2/4] 内核自检（防 MPS/SDPA 内核回归）")
    torch = _load_torch()
    if torch is None:
        skip("内核自检用例", "缺 torch")
        return

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "mps" else torch.float32

    result = sidecar.run_kernel_selftest(torch, device, dtype)
    check(
        f"生产配置自检通过（{device}/{result['dtype']}）",
        result["status"] == "ok",
        str(result),
    )
    check(
        "自检记录了 seq_lens / head_dim / rel_err",
        result["seq_lens"] == list(sidecar.SELFTEST_SEQ_LENS)
        and result["head_dim"] == sidecar.SELFTEST_HEAD_DIM
        and result["max_rel_err"] is not None,
        str(result),
    )
    check(
        f"自检 rel_err 远低于阈值（{result['max_rel_err']} ≤ {sidecar.SELFTEST_MAX_REL_ERR}）",
        (result["max_rel_err"] or 0) <= sidecar.SELFTEST_MAX_REL_ERR,
        str(result["max_rel_err"]),
    )
    cpu_result = sidecar.run_kernel_selftest(torch, "cpu", torch.float32)
    check(
        "CPU fp32 自检 rel_err == 0（基准与被测在 CPU fp32 上一致）",
        cpu_result["max_rel_err"] == 0.0,
        str(cpu_result),
    )

    # 失败分支：只把 SDPA 换成坏内核（其余算子真实），必须报 failed 且不抛异常
    broken = sidecar.run_kernel_selftest(_BrokenTorchShim(torch), "cpu", torch.float32)
    check("坏内核被判定为 failed", broken["status"] == "failed", str(broken))
    check(
        "坏内核 rel_err 超过阈值",
        (broken["max_rel_err"] or 0) > sidecar.SELFTEST_MAX_REL_ERR,
        str(broken["max_rel_err"]),
    )
    check(
        "自检覆盖多个序列长度（含 17/24/32）",
        [item["seq_len"] for item in result["per_seq"]] == list(sidecar.SELFTEST_SEQ_LENS),
        str([item["seq_len"] for item in result["per_seq"]]),
    )
    check(
        "自检 head_dim 与真实模型一致（128）",
        result["head_dim"] == 128,
        str(result["head_dim"]),
    )


# --------------------------------------------------------------------------
# 第 3 层：真实模型一致性 / 基准 / 检索
# --------------------------------------------------------------------------


def _load_transformers():
    try:
        sidecar._shield_broken_optional_deps()
        from transformers import AutoTokenizer
    except Exception as exc:  # noqa: BLE001 —— 缺依赖一律 SKIP
        print(f"  依赖不可用：{type(exc).__name__}: {exc}")
        return None
    return AutoTokenizer


def make_text_with_tokens(tokenizer, seed_text: str, target_tokens: int) -> str:
    """构造一个「重新分词后恰好 target_tokens 个 token」的文本。

    用于精确制造 **等长批量（无 padding）** 与 **指定长度**（≥17/24/32）样本。
    直接从 token id 截断再 decode，并回验真实长度；round-trip 有 ±1 偏差时
    就近微调截断点。
    """
    ids = list(tokenizer(seed_text, add_special_tokens=False)["input_ids"])
    while len(ids) < target_tokens:
        ids = ids + ids
    for cut in (
        target_tokens,
        target_tokens + 1,
        target_tokens - 1,
        target_tokens + 2,
        target_tokens - 2,
    ):
        if cut <= 0 or cut > len(ids):
            continue
        text = tokenizer.decode(ids[:cut])
        got = len(tokenizer(text, add_special_tokens=True)["input_ids"])
        if got == target_tokens:
            return text
    return tokenizer.decode(ids[:target_tokens])


def _token_len(tokenizer, text: str) -> int:
    return len(tokenizer(text, add_special_tokens=True)["input_ids"])


def _capture_prepared(embedder, texts: list[str], input_type: str) -> list[str]:
    """spy ``LocalEmbedder._run_batches``，返回真正送入模型的文本列表。

    这是 P3-1 的关键手段：只断言「向量不同 / 长度够」属于**结果层**观察，
    无法区分"前缀写错但仍是另一个不同的长串"；只有拿到送给 tokenizer 的
    原文，才能在**文本层**逐字验证前缀内容、位置与 query/document 归属。

    spy 只记录入参并原样转发，不改变推理行为；异常路径用 finally 复原。
    """
    captured: list[str] = []
    original = embedder._run_batches

    def spy(prepared: list[str]):
        captured.extend(prepared)
        return original(prepared)

    embedder._run_batches = spy
    try:
        embedder.embed(texts, input_type)
    finally:
        embedder._run_batches = original
    return captured


def test_model() -> None:
    print("\n[3/4] 模型层（真实 Qwen3-Embedding-0.6B）")
    torch = _load_torch()
    tokenizer_cls = _load_transformers()
    if torch is None or tokenizer_cls is None:
        skip("模型层全部用例", "缺 torch/transformers")
        return
    model_dir = sidecar.resolve_model_dir()
    if not model_dir.is_dir():
        skip("模型层全部用例", f"模型目录不存在：{model_dir}")
        return
    print(f"  使用模型目录：{model_dir}")

    tokenizer = tokenizer_cls.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False
    )

    embedder = sidecar.LocalEmbedder(model_dir, batch_size=8)
    if not embedder.load():
        check("模型加载成功", False, str(embedder.error))
        return
    check("模型加载成功", True, f"device={embedder.device} dtype={embedder.dtype_name}")

    health = embedder.health()
    check("健康检查 dim == 1024", health["dim"] == 1024, str(health["dim"]))
    check("设备为 mps 或 cpu", health["device"] in ("mps", "cpu"), str(health["device"]))
    check(
        "加载后 /health 的 selftest 为 ok",
        health.get("selftest") == "ok",
        str(health.get("selftest_detail")),
    )

    # ---- 长度覆盖：≥17 / ≥24 / ≥32 token（历史 MPS SDPA bug 的触发区间）----
    lengths = {"keyboard": 17, "laptop": 24, "card": 32}
    length_texts: dict[str, str] = {}
    for key, target in lengths.items():
        text = make_text_with_tokens(tokenizer, SEEDS[key], target)
        actual = _token_len(tokenizer, text)
        length_texts[key] = text
        check(f"{key} 样本长度 == {target} token", actual == target, f"实际 {actual} token")

    # ---- 三方一致性：单条 vs 等长批量（无 padding）vs 混合批量（有 padding）----
    equal_len = 24
    equal_texts = [
        make_text_with_tokens(tokenizer, SEEDS["keyboard"], equal_len),
        make_text_with_tokens(tokenizer, SEEDS["laptop"], equal_len),
        make_text_with_tokens(tokenizer, SEEDS["card"], equal_len),
    ]
    equal_lengths = [_token_len(tokenizer, text) for text in equal_texts]
    check(
        "等长批量三条长度相同（无 padding）",
        len(set(equal_lengths)) == 1 and equal_lengths[0] == equal_len,
        str(equal_lengths),
    )

    # 混合批量 = 同一批 equal_texts + 一条更长的填充文本（长度 32）：
    # 这样 batch 内必然产生 padding，但被比较的仍是**同一批文本**，
    # 差异只可能来自 padding / 长序列内核路径，而不是文本不同。
    padding_text = make_text_with_tokens(tokenizer, SEEDS["book"], 32)
    mixed_texts = [*equal_texts, padding_text]
    mixed_lengths = [_token_len(tokenizer, text) for text in mixed_texts]
    check(
        "混合批量长度不全相同（必然 padding）",
        len(set(mixed_lengths)) > 1,
        str(mixed_lengths),
    )

    equal_batch = embedder.embed(equal_texts).vectors
    mixed_batch = embedder.embed(mixed_texts).vectors[: len(equal_texts)]  # 只取同文本部分
    singles = [embedder.embed([text]).vectors[0] for text in equal_texts]

    singles_vs_equal = [cosine(a, b) for a, b in zip(singles, equal_batch, strict=True)]
    singles_vs_mixed = [cosine(a, b) for a, b in zip(singles, mixed_batch, strict=True)]
    equal_vs_mixed = [cosine(a, b) for a, b in zip(equal_batch, mixed_batch, strict=True)]
    check(
        "单条 vs 等长批量（无 padding）cosine ≥ 0.99",
        min(singles_vs_equal) >= CONSISTENCY_MIN_COS,
        f"最低 {min(singles_vs_equal):.6f}",
    )
    check(
        "单条 vs 混合批量（有 padding）cosine ≥ 0.99",
        min(singles_vs_mixed) >= CONSISTENCY_MIN_COS,
        f"最低 {min(singles_vs_mixed):.6f}",
    )
    check(
        "等长批量 vs 混合批量 cosine ≥ 0.99",
        min(equal_vs_mixed) >= CONSISTENCY_MIN_COS,
        f"最低 {min(equal_vs_mixed):.6f}",
    )
    print(
        "    三方一致性最低 cosine："
        f"{min(min(singles_vs_equal), min(singles_vs_mixed), min(equal_vs_mixed)):.6f}"
    )

    # ---- 长度覆盖：≥17/≥24/≥32 token 各长度「单条 vs 变长批量」都必须一致 ----
    varied_texts = [length_texts[key] for key in lengths]
    varied_batch = embedder.embed(varied_texts).vectors
    varied_sims = []
    for index, (key, target) in enumerate(lengths.items()):
        single = embedder.embed([length_texts[key]]).vectors[0]
        sim = cosine(single, varied_batch[index])
        varied_sims.append(sim)
        check(
            f"长度 {target} token：单条 vs 变长批量 cosine ≥ 0.99",
            sim >= CONSISTENCY_MIN_COS,
            f"{sim:.6f}",
        )
    print("    长度覆盖组最低 cosine：" + f"{min(varied_sims):.6f}")

    # ---- 跨设备/跨精度对照：同实现跑 CPU fp32（同一批 mixed_texts，含 padding）----
    # 定位说明（P3-2，避免夸大）：这是 **同一个 LocalEmbedder 实现**，仅切换
    # device/dtype，因此它只能捕获"设备或精度相关的内核 bug"（如 MPS bf16
    # SDPA 算错），**不能**发现池化索引、归一化方向这类算法逻辑错误——
    # 后者由下方"独立参考实现"与内核自检的手算基准负责。
    cpu_embedder = sidecar.LocalEmbedder(model_dir, device="cpu", batch_size=8)
    if not cpu_embedder.load():
        skip("跨设备/跨精度对照", str(cpu_embedder.error))
    else:
        cpu_vectors = cpu_embedder.embed(mixed_texts).vectors
        device_vectors = embedder.embed(mixed_texts).vectors
        baseline_sims = [
            cosine(device_vec, cpu_vec)
            for device_vec, cpu_vec in zip(device_vectors, cpu_vectors, strict=True)
        ]
        check(
            f"{embedder.device}/{embedder.dtype_name} vs 同实现 CPU fp32 cosine ≥ 0.99",
            min(baseline_sims) >= BASELINE_MIN_COS,
            f"最低 {min(baseline_sims):.6f}",
        )
        print(f"    设备 vs 同实现 CPU fp32 最低 cosine：{min(baseline_sims):.6f}")

    # ---- 批量内所有向量归一化 + 维度 ----
    all_vectors = equal_batch + mixed_batch
    check(
        "批量向量均 1024 维",
        all(len(vector) == 1024 for vector in all_vectors),
        str(sorted({len(vector) for vector in all_vectors})),
    )
    check(
        "批量向量均已归一化",
        all(abs(l2_norm(vector) - 1.0) < 1e-3 for vector in all_vectors),
        f"范数范围 {min(l2_norm(v) for v in all_vectors):.4f}–"
        f"{max(l2_norm(v) for v in all_vectors):.4f}",
    )
    check("所有分量为有限值", all(math.isfinite(x) for v in all_vectors for x in v))

    # ---- query 前缀：文本层断言（P3-1 补盲区）----
    # 光有「query≠document 向量」「前缀长度」这类**结果层**断言，抓不到
    # 「前缀被换成短错串 / 拼到文本之后 / query 与 document 互换」——
    # 三者都能让向量变得"不同且够长"，测试照样全绿。所以必须 spy 真正送入
    # 模型的文本（_run_batches 的入参），在**文本层**逐字断言。
    prompts_path = model_dir / "config_sentence_transformers.json"
    prompts_json = json.loads(prompts_path.read_text(encoding="utf-8")).get("prompts") or {}
    check(
        "query_prefix 与模型 config_sentence_transformers.json 的 prompts.query 逐字一致",
        embedder.query_prefix == prompts_json.get("query"),
        f"实际 {embedder.query_prefix!r} vs 期望 {prompts_json.get('query')!r}",
    )
    check(
        "query_prefix 非空且含 Instruct/Query 结构",
        bool(embedder.query_prefix)
        and "Instruct:" in embedder.query_prefix
        and embedder.query_prefix.rstrip().endswith("Query:"),
        repr(embedder.query_prefix),
    )
    check(
        "document_prefix 与 prompts.document 逐字一致",
        embedder.document_prefix == (prompts_json.get("document") or ""),
        repr(embedder.document_prefix),
    )

    query_text = "想买个便宜的机械键盘"
    query_prepared = _capture_prepared(embedder, [query_text], "query")
    doc_prepared = _capture_prepared(embedder, [query_text], "document")
    check("spy 抓到 query 路径的送模型文本", len(query_prepared) == 1, str(query_prepared))
    check(
        "query 送模型文本 == query_prefix + 原文（前缀在前、逐字拼接）",
        query_prepared[0] == embedder.query_prefix + query_text,
        f"实际 {query_prepared[0]!r}",
    )
    check(
        "query 送模型文本以 query_prefix 开头",
        query_prepared[0].startswith(embedder.query_prefix),
        repr(query_prepared[0][:60]),
    )
    check(
        "query 送模型文本不以 query_prefix 结尾（排除后置拼接）",
        not query_prepared[0].endswith(embedder.query_prefix),
        repr(query_prepared[0][-60:]),
    )
    check(
        "query 送模型文本中前缀只出现一次",
        query_prepared[0].count(embedder.query_prefix) == 1,
        str(query_prepared[0].count(embedder.query_prefix)),
    )
    check(
        "document 送模型文本不带 query 前缀",
        not doc_prepared[0].startswith(embedder.query_prefix),
        repr(doc_prepared[0][:60]),
    )
    check(
        "query 送模型文本 != document 送模型文本（路径确实不同）",
        query_prepared[0] != doc_prepared[0],
        "两者相同",
    )

    # 哨兵前缀：把两个前缀临时换成可区分的标记，验证「query 取 query_prefix、
    # document 取 document_prefix」的选择逻辑本身（不依赖模型 json 里
    # document 恰为空——本例 document_prefix 就是 ""，光看真实配置会漏掉
    # 「document 也用了 query 前缀」这类错误）。
    original_query_prefix, original_doc_prefix = embedder.query_prefix, embedder.document_prefix
    sentinel_query, sentinel_doc = "[[Q-SENTINEL]]", "[[D-SENTINEL]]"
    try:
        embedder.query_prefix = sentinel_query
        embedder.document_prefix = sentinel_doc
        sentinel_q = _capture_prepared(embedder, ["文本"], "query")
        sentinel_d = _capture_prepared(embedder, ["文本"], "document")
    finally:
        embedder.query_prefix = original_query_prefix
        embedder.document_prefix = original_doc_prefix
    check(
        "query 路径取 query_prefix（哨兵验证）",
        sentinel_q[0] == sentinel_query + "文本",
        repr(sentinel_q[0]),
    )
    check(
        "document 路径取 document_prefix（哨兵验证）",
        sentinel_d[0] == sentinel_doc + "文本",
        repr(sentinel_d[0]),
    )
    check(
        "两个前缀未互换（哨兵验证）",
        not sentinel_q[0].startswith(sentinel_doc) and not sentinel_d[0].startswith(sentinel_query),
        f"query={sentinel_q[0]!r} document={sentinel_d[0]!r}",
    )
    check(
        "探针后前缀已复原",
        embedder.query_prefix == original_query_prefix
        and embedder.document_prefix == original_doc_prefix,
        "前缀未复原",
    )

    query_vec = embedder.embed([query_text], "query").vectors[0]
    doc_vec = embedder.embed([query_text], "document").vectors[0]
    query_doc_sim = cosine(query_vec, doc_vec)
    check("query 与 document 向量不同", query_doc_sim < 0.9999, f"{query_doc_sim:.6f}")
    check("query 向量已归一化", abs(l2_norm(query_vec) - 1.0) < 1e-3, f"{l2_norm(query_vec):.6f}")

    query_batch = embedder.embed([query_text, "出个笔记本"], "query").vectors
    query_single_sims = [
        cosine(query_vec, query_batch[0]),
        cosine(embedder.embed(["出个笔记本"], "query").vectors[0], query_batch[1]),
    ]
    check(
        "query 批量 vs 单条 cosine ≥ 0.99",
        min(query_single_sims) >= CONSISTENCY_MIN_COS,
        f"最低 {min(query_single_sims):.6f}",
    )
    prefix_len = _token_len(tokenizer, embedder.query_prefix + query_text)
    check(
        f"query 实际长度 {prefix_len} token（前缀已把序列推入长序列区间）",
        prefix_len >= 24,
        str(prefix_len),
    )

    # ---- 池化/归一化的独立参考实现（P3-2：这才是真正的独立实现对照）----
    # 不复用 LocalEmbedder._run_batches，而是直接 forward + 逐条取末 token +
    # 手写 L2 归一化，与 embedder.embed 的结果比对，隔离「池化索引/归一化」
    # 这类算法逻辑错误（CPU fp32 对照只能防设备内核 bug）。
    ref_sims = []
    with torch.inference_mode():
        for text in equal_texts:
            encoded = embedder._tokenizer(
                [text], padding=False, truncation=True, max_length=512, return_tensors="pt"
            )
            encoded = {key: value.to(embedder.device) for key, value in encoded.items()}
            output = embedder._model(**encoded)
            hidden = output.last_hidden_state
            mask = encoded["attention_mask"][0]
            last_valid = int(mask.nonzero()[-1].item())  # 显式定位最后一个有效 token
            pooled = hidden[0, last_valid].float()
            norm = pooled.norm(p=2)
            reference = (pooled / norm).detach().to("cpu").tolist()
            ref_sims.append(cosine(reference, embedder.embed([text]).vectors[0]))
    check(
        "独立参考实现（手写 last-token + L2）与 embed 结果 cosine ≥ 0.999",
        min(ref_sims) >= 0.999,
        f"最低 {min(ref_sims):.6f}",
    )
    print(f"    独立参考实现最低 cosine：{min(ref_sims):.6f}")

    # ---- 检索排序：query 应把同主题文档排在前面 ----
    docs = [
        "罗技 K845 机械键盘 青轴 九成新 宿舍自提 可小刀 配件齐全",  # 0 键盘
        "樱桃 MX 机械键盘 红轴 毕业出 键帽全套 手感极佳 价格好谈",  # 1 键盘
        "苹果 MacBook Air M2 十六 G 内存 深空灰 电池健康 电池循环少",  # 2 笔记本
        "联想拯救者 Y7000P 游戏本 i7 处理器 独立显卡 九成新",  # 3 笔记本
        "食堂饭卡 余额五十元 可直接刷卡 毕业离校转让 教学楼当面交易",  # 4 饭卡
        "微积分教材 同济版 第七版 上下册 笔记齐全 无破损 考研必备",  # 5 教材
    ]
    doc_vectors = embedder.embed(docs).vectors

    def rank(query: str) -> list[float]:
        query_vec = embedder.embed([query], "query").vectors[0]
        return [cosine(query_vec, vec) for vec in doc_vectors]

    # 检索断言刻意选**无歧义**的 query：中文「笔记本」既可指电脑也可指纸本，
    # 拿它断言排序会把语言学歧义误判成模型缺陷（实测「出个笔记本」在
    # document 模式下确实把键盘排在前面）。这里改用「笔记本电脑」「游戏本」
    # 这类指向明确的说法。
    keyboard_scores = rank("想买个便宜的机械键盘")
    laptop_scores = rank("想买台二手笔记本电脑")
    card_scores = rank("食堂饭卡转让")
    book_scores = rank("二手微积分教材")
    for label, scores in (
        ("想买个便宜的机械键盘", keyboard_scores),
        ("想买台二手笔记本电脑", laptop_scores),
        ("食堂饭卡转让", card_scores),
        ("二手微积分教材", book_scores),
    ):
        print(f"    query「{label}」得分：" + " / ".join(f"{score:.4f}" for score in scores))

    check(
        "键盘 query：Top-2 恰好是两条键盘文档",
        set(sorted(range(len(keyboard_scores)), key=lambda i: -keyboard_scores[i])[:2]) == {0, 1},
        str([round(score, 4) for score in keyboard_scores]),
    )
    check(
        "笔记本 query：两台笔记本占据 Top-2",
        set(sorted(range(len(laptop_scores)), key=lambda i: -laptop_scores[i])[:2]) == {2, 3},
        str([round(score, 4) for score in laptop_scores]),
    )
    check(
        "饭卡 query：饭卡文档排第一且显著领先",
        card_scores.index(max(card_scores)) == 4 and card_scores[4] > 0.5,
        str([round(score, 4) for score in card_scores]),
    )
    check(
        "教材 query：教材文档排第一",
        book_scores.index(max(book_scores)) == 5,
        str([round(score, 4) for score in book_scores]),
    )
    check(
        "不同 query 的最优命中不同（query 侧信息真实生效）",
        len(
            {
                keyboard_scores.index(max(keyboard_scores)),
                laptop_scores.index(max(laptop_scores)),
                card_scores.index(max(card_scores)),
                book_scores.index(max(book_scores)),
            }
        )
        == 4,
        "四个 query 的最优命中应互不相同",
    )

    result = embedder.embed(["罗技机械键盘 九成新"])
    check("单条输入返回 1 个向量", len(result.vectors) == 1)
    check("prompt_tokens > 0", result.prompt_tokens > 0, str(result.prompt_tokens))

    global REAL_EMBEDDER
    REAL_EMBEDDER = embedder


REAL_EMBEDDER = None


# --------------------------------------------------------------------------
# 第 4 层：端到端
# --------------------------------------------------------------------------


def test_end_to_end() -> None:
    print("\n[4/4] 端到端（真模型 + 真实 HTTP）")
    if REAL_EMBEDDER is None:
        skip("端到端用例", "模型层未通过/未执行")
        return

    with Sidecar(REAL_EMBEDDER) as car:
        status, health = request(car.base, "/health")
        check("端到端 /health 200", status == 200, f"实际 {status}")
        check("端到端 health.dim == 1024", health.get("dim") == 1024, str(health.get("dim")))
        check(
            "端到端 health.selftest == ok",
            health.get("selftest") == "ok",
            str(health.get("selftest_detail")),
        )
        check(
            "端到端 health 含 device/dtype",
            health.get("device") in ("mps", "cpu") and health.get("dtype"),
            str((health.get("device"), health.get("dtype"))),
        )

        status, models_body = request(car.base, "/v1/models")
        check("端到端 GET /v1/models 200", status == 200, f"实际 {status}")
        check(
            "端到端 models 含真实模型名",
            models_body.get("data", [{}])[0].get("id") == REAL_EMBEDDER.model_name,
            str(models_body),
        )

        status, body = request(
            car.base,
            "/v1/embeddings",
            method="POST",
            payload={"input": ["罗技机械键盘 九成新", "苹果笔记本", "食堂饭卡"], "model": "local"},
        )
        check("端到端 embeddings 200", status == 200, f"实际 {status}")
        if status == 200:
            vectors = [item["embedding"] for item in body["data"]]
            dims = [len(v) for v in vectors]
            check("端到端 3 条 × 1024 维", dims == [1024] * 3, str(dims))
            check(
                "端到端向量均已归一化",
                all(abs(l2_norm(vector) - 1.0) < 1e-3 for vector in vectors),
                str([round(l2_norm(v), 4) for v in vectors]),
            )
            print(f"    第 1 条前 5 维：{[round(x, 6) for x in vectors[0][:5]]}")
            print(
                f"    两两余弦：键盘-笔记本 {cosine(vectors[0], vectors[1]):.4f}"
                f" / 键盘-饭卡 {cosine(vectors[0], vectors[2]):.4f}"
                f" / 笔记本-饭卡 {cosine(vectors[1], vectors[2]):.4f}"
            )

        # 端到端 keep-alive：正常请求后同连接可继续复用（200 不需要断连）
        first, second = raw_keepalive_probe(
            car.port,
            _post_request("/v1/embeddings", '{"input":["keep-alive 测试"]}'.encode()),
            b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
        )
        check(
            "200 请求后同连接可继续复用（keep-alive 保留）",
            first.startswith(b"HTTP/1.1 200") and second.startswith(b"HTTP/1.1 200"),
            f"{first[:20]!r} / {second[:20]!r}",
        )


# --------------------------------------------------------------------------


def main() -> int:
    print("本地 Embedding 侧车自测（Qwen3-Embedding-0.6B）")
    print(f"模型目录（探测结果）：{sidecar.resolve_model_dir()}")
    started = time.perf_counter()
    test_protocol()
    test_kernel_selftest()
    test_model()
    test_end_to_end()
    elapsed = time.perf_counter() - started

    print("\n" + "=" * 60)
    print(
        f"通过 {len(PASSED)} 项，跳过 {len(SKIPPED)} 项，失败 {len(FAILED)} 项，耗时 {elapsed:.1f}s"
    )
    for item in SKIPPED:
        print(f"  SKIP {item}")
    for item in FAILED:
        print(f"  FAIL {item}")
    if FAILED:
        print("结果：FAILED")
        return 1
    if SKIPPED:
        print("结果：部分跳过（依赖未就绪）——协议层已通过")
    else:
        print("结果：全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

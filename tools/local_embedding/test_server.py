"""本地 Embedding 侧车自测脚本（不依赖 pytest，缺失依赖时打印 SKIP 并以 0 退出）。

用法::

    ~/my/torch_python/.venv/bin/python test_server.py

分三层：

1. **协议层（无依赖）**：用假 embedder（FakeEmbedder）起真实 HTTP 服务，
   校验 /health、/v1/embeddings 的请求解析、错误码、OpenAI 响应结构。
   这一层即使没装 torch/transformers 也会完整执行。
2. **模型层（需 torch + transformers + 本地模型）**：直接驱动 LocalEmbedder，
   校验 1024 维、L2 范数≈1、批量 right-padding 与单条结果一致、
   query/document 前缀差异、中文语义近似度排序。
3. **端到端**：真模型 + 真实 HTTP 往返（HTTP 层与协议层用同一份 handler）。

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
        self._ready = ready
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
        }
        if not self._ready:
            body["error"] = self.error
        return body

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
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


def l2_norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


# --------------------------------------------------------------------------
# 第 1 层：协议层
# --------------------------------------------------------------------------


def test_protocol() -> None:
    print("\n[1/3] 协议层（假 embedder，无需模型）")

    with Sidecar(FakeEmbedder()) as car:
        status, body = request(car.base, "/health")
        check("GET /health 返回 200", status == 200, f"实际 {status}")
        check("health.status == ok", body.get("status") == "ok", str(body))
        check("health.dim == 1024", body.get("dim") == 1024, str(body.get("dim")))

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
        check("合法请求 400 用例后仍可用", status == 200)

        status, body = request(car.base, "/v1/embeddings")
        check("GET /v1/embeddings → 405", status == 405, f"实际 {status}")

        status, body = request(car.base, "/no-such")
        check("未知路径 → 404", status == 404, f"实际 {status}")

    # 模型未就绪：/health 503，embeddings 503，进程不崩
    with Sidecar(FakeEmbedder(ready=False)) as car:
        status, body = request(car.base, "/health")
        check("模型未就绪 /health 返回 503", status == 503, f"实际 {status}")
        check("503 响应带结构化 error", isinstance(body.get("error"), dict), str(body))
        status, body = request(car.base, "/v1/embeddings", method="POST", payload={"input": ["x"]})
        check("模型未就绪 /v1/embeddings 返回 503", status == 503, f"实际 {status}")

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
# 第 2、3 层：真实模型
# --------------------------------------------------------------------------


def _load_deps() -> tuple[object, object] | None:
    """探测 torch + transformers；缺失返回 None（调用方打印 SKIP）。"""
    try:
        sidecar._disable_broken_optional_deps()
        import torch
        from transformers import AutoModel, AutoTokenizer  # noqa: F401
    except Exception as exc:  # noqa: BLE001 —— 缺依赖一律 SKIP
        print(f"  依赖不可用：{type(exc).__name__}: {exc}")
        return None
    return torch, AutoModel


def test_model() -> None:
    print("\n[2/3] 模型层（真实 Qwen3-Embedding-0.6B）")
    if _load_deps() is None:
        skip("模型层全部用例", "缺 torch/transformers 或扩展损坏")
        return
    model_dir = sidecar.resolve_model_dir()
    if not model_dir.is_dir():
        skip("模型层全部用例", f"模型目录不存在：{model_dir}")
        return
    print(f"  使用模型目录：{model_dir}")

    embedder = sidecar.LocalEmbedder(model_dir, batch_size=8)
    if not embedder.load():
        check("模型加载成功", False, str(embedder.error))
        return
    check("模型加载成功", True, f"device={embedder.device} dtype={embedder.dtype_name}")

    health = embedder.health()
    check("健康检查 dim == 1024", health["dim"] == 1024, str(health["dim"]))
    check("设备为 mps 或 cpu", health["device"] in ("mps", "cpu"), str(health["device"]))

    result = embedder.embed(["罗技机械键盘 九成新"])
    check("单条输入返回 1 个向量", len(result.vectors) == 1)
    check("向量维度 == 1024", len(result.vectors[0]) == 1024, str(len(result.vectors[0])))
    norm = l2_norm(result.vectors[0])
    check("L2 范数 ≈ 1.0", abs(norm - 1.0) < 1e-3, f"{norm:.6f}")
    check("所有分量为有限值", all(math.isfinite(value) for value in result.vectors[0]))
    check("prompt_tokens > 0", result.prompt_tokens > 0, str(result.prompt_tokens))

    # 批量（不同长度，测 right padding 下 last-token 定位）与单条结果一致
    texts = ["罗技机械键盘 九成新，青轴", "苹果笔记本", "食堂饭卡 已充值五十元"]
    batched = embedder.embed(texts)
    check("批量返回条数一致", len(batched.vectors) == 3, str(len(batched.vectors)))
    check(
        "批量向量均 1024 维",
        all(len(vector) == 1024 for vector in batched.vectors),
        str([len(vector) for vector in batched.vectors]),
    )
    singles = [embedder.embed([text]).vectors[0] for text in texts]
    deviations = [
        max(abs(a - b) for a, b in zip(batch_vec, single, strict=True))
        for batch_vec, single in zip(batched.vectors, singles, strict=True)
    ]
    check(
        "批量与单条结果一致（padding 不影响 last-token 池化）",
        all(deviation < 2e-2 for deviation in deviations),
        f"最大偏差 {max(deviations):.4f}",
    )

    # 语义：同主题（键盘/数码）应高于无关主题（饭卡）
    keyboard, laptop, card = batched.vectors
    same_topic = cosine(keyboard, laptop)
    cross_topic = max(cosine(keyboard, card), cosine(laptop, card))
    check(
        "同主题相似度 > 无关主题",
        same_topic > cross_topic + 0.05,
        f"同主题 {same_topic:.4f} vs 无关 {cross_topic:.4f}",
    )

    # query / document 前缀产生不同向量（且各自归一化）
    as_query = embedder.embed(["机械键盘"], "query").vectors[0]
    as_doc = embedder.embed(["机械键盘"], "document").vectors[0]
    query_doc_sim = cosine(as_query, as_doc)
    check("query 与 document 向量不同", query_doc_sim < 0.9999, f"{query_doc_sim:.6f}")
    check("query 向量同样归一化", abs(l2_norm(as_query) - 1.0) < 1e-3, f"{l2_norm(as_query):.6f}")

    global REAL_EMBEDDER
    REAL_EMBEDDER = embedder


REAL_EMBEDDER = None


def test_end_to_end() -> None:
    print("\n[3/3] 端到端（真模型 + 真实 HTTP）")
    if REAL_EMBEDDER is None:
        skip("端到端用例", "模型层未通过/未执行")
        return

    with Sidecar(REAL_EMBEDDER) as car:
        status, health = request(car.base, "/health")
        check("端到端 /health 200", status == 200, f"实际 {status}")
        check("端到端 health.dim == 1024", health.get("dim") == 1024, str(health.get("dim")))

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


# --------------------------------------------------------------------------


def main() -> int:
    print("本地 Embedding 侧车自测（Qwen3-Embedding-0.6B）")
    print(f"模型目录（探测结果）：{sidecar.resolve_model_dir()}")
    started = time.perf_counter()
    test_protocol()
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

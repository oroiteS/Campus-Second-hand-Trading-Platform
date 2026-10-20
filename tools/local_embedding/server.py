"""本地 Embedding 侧车服务（OpenAI 兼容）——加载本机 Qwen3-Embedding-0.6B。

设计要点（详见同目录 README.md）：

- 运行在独立的 Python 3.10 + torch 环境（``~/my/torch_python/.venv``），
  与 Flask 后端（3.12、无 torch）运行时不同，因此独立成 ``tools/local_embedding/``，
  不放进 ``campus_backend/src/``；后端只经 HTTP 调用本服务。
- 仅用标准库 ``http.server`` 实现 HTTP 层，不引入 Flask 等额外依赖。
- ``POST /v1/embeddings`` 兼容 OpenAI 语义（``input`` 为字符串或字符串数组），
  额外支持非标准字段 ``input_type``（query / document）选择是否加查询指令前缀。
- 池化按模型自身配置：last-token pooling（用 attention_mask 定位最后一个有效
  token）+ L2 归一化，输出固定 1024 维（与后端 ``EMBEDDING_DIM`` 一致）。
- 模型加载失败时进程不退出：``GET /health`` 返回 503 且带结构化错误。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

LOGGER = logging.getLogger("local_embedding")

# tools/local_embedding/server.py -> 仓库检出根（模型目录与之平级）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR_NAME = "qwen3_embedding_0_6b"
# 模型目录候选顺序：检出根平级（主仓/正常检出）、再向上一层（worktree 检出时
# 模型只在主仓根目录，主仓根即 worktree 根的上两级）、最后用户家目录。
MODEL_DIR_CANDIDATES = (
    PROJECT_ROOT / MODEL_DIR_NAME,
    PROJECT_ROOT.parents[1] / MODEL_DIR_NAME,
    Path.home() / MODEL_DIR_NAME,
)
DEFAULT_MODEL_DIR = MODEL_DIR_CANDIDATES[0]
DEFAULT_MODEL_NAME = MODEL_DIR_NAME

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8010  # 避开后端 5000/5010/5020/5030 与前端 5173/5180/5190/5200
DEFAULT_BATCH_SIZE = 32
DEFAULT_MAX_LENGTH = 512
EMBEDDING_DIM = 1024  # 与 campus_backend 的 EMBEDDING_DIM、Chroma 集合维度一致
MAX_REQUEST_BYTES = 8 * 1024 * 1024

# 模型 config_sentence_transformers.json 的 prompts.query 原文（读不到时回退）
QUERY_INSTRUCTION_FALLBACK = (
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
)
VALID_INPUT_TYPES = ("query", "document")


# --------------------------------------------------------------------------
# 错误类型
# --------------------------------------------------------------------------


class EmbeddingRequestError(ValueError):
    """请求非法（映射为 400，OpenAI 风格的 error 体）。"""

    def __init__(self, message: str, *, param: str | None = None, code: str = "invalid_request"):
        super().__init__(message)
        self.message = message
        self.param = param
        self.code = code


class EmbeddingUnavailable(RuntimeError):
    """模型未就绪（映射为 503）。"""


# --------------------------------------------------------------------------
# 结果与请求体
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EmbeddingResult:
    """一次向量化的结果：向量列表 + 有效 token 数（用于 usage 统计）。"""

    vectors: list[list[float]]
    prompt_tokens: int


@dataclass(frozen=True)
class EmbeddingRequest:
    """解析后的 ``/v1/embeddings`` 请求。"""

    texts: list[str]
    input_type: str
    dimensions: int | None
    model: str | None


def parse_embedding_request(payload: Any) -> EmbeddingRequest:
    """校验并规范化 OpenAI 风格的 embeddings 请求体。

    ``input`` 支持字符串与字符串数组（OpenAI 语义）；空数组、非字符串元素、
    空白文本一律拒绝（避免产出无意义的 1-token 向量）。``dimensions`` 只接受
    等于 1024（本模型原生维度），不做 Matryoshka 截断，保证与 Chroma 集合一致。
    """
    if not isinstance(payload, dict):
        raise EmbeddingRequestError("请求体必须是 JSON 对象", param=None)

    raw_input = payload.get("input")
    if isinstance(raw_input, str):
        texts = [raw_input]
    elif isinstance(raw_input, list):
        if not raw_input:
            raise EmbeddingRequestError("input 不能为空数组", param="input", code="empty_input")
        texts = []
        for index, item in enumerate(raw_input):
            if not isinstance(item, str):
                raise EmbeddingRequestError(f"input[{index}] 必须是字符串", param=f"input[{index}]")
            texts.append(item)
    else:
        raise EmbeddingRequestError(
            "input 必须是字符串或字符串数组", param="input", code="invalid_input"
        )

    normalized: list[str] = []
    for index, text in enumerate(texts):
        stripped = text.strip()
        if not stripped:
            raise EmbeddingRequestError(
                f"input[{index}] 不能是空文本", param=f"input[{index}]", code="empty_input"
            )
        normalized.append(text)

    input_type = payload.get("input_type", "document")
    if input_type is None:
        input_type = "document"
    if input_type not in VALID_INPUT_TYPES:
        raise EmbeddingRequestError(
            "input_type 只支持 'query' 或 'document'",
            param="input_type",
            code="invalid_input_type",
        )

    dimensions = payload.get("dimensions")
    if dimensions is not None:
        if not isinstance(dimensions, int) or isinstance(dimensions, bool):
            raise EmbeddingRequestError("dimensions 必须是整数", param="dimensions")
        if dimensions != EMBEDDING_DIM:
            raise EmbeddingRequestError(
                f"dimensions 只支持 {EMBEDDING_DIM}（本模型原生维度，不做截断）",
                param="dimensions",
                code="unsupported_dimensions",
            )

    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        raise EmbeddingRequestError("model 必须是字符串", param="model")

    return EmbeddingRequest(
        texts=normalized, input_type=input_type, dimensions=dimensions, model=model
    )


# --------------------------------------------------------------------------
# 真实模型推理
# --------------------------------------------------------------------------


def _disable_broken_optional_deps() -> list[str]:
    """屏蔽“装了但导入即失败”的可选依赖，避免拖垮 transformers 导入。

    本机事实（2026-10 实测）：``scipy 1.15.3`` 的 ``_propack`` 扩展在 macOS
    上动态库损坏，``import scipy.sparse`` 直接 ImportError；``sklearn`` 因此也
    导入失败。而 ``transformers``（5.20.2）在 **模块导入期** 就无条件
    ``from sklearn.metrics import roc_curve``（``candidate_generator``）与
    ``from scipy.optimize import ...``（``loss_for_object_detection``），且其
    ``is_*_available()`` 用 ``importlib.util.find_spec`` 探测——把不可用的包在
    ``sys.modules`` 里置 ``None`` 后 find_spec 返回 None，transformers 即跳过。

    只对“探测导入已经失败”的包生效，可用的包不受影响；侧车推理不需要
    scipy/sklearn，屏蔽无副作用。包修好后本函数自动变成 no-op。
    """
    disabled: list[str] = []
    for name, probe in (("scipy", "scipy.sparse"), ("sklearn", "sklearn.metrics")):
        try:
            __import__(probe)
        except Exception as exc:  # noqa: BLE001 —— 任何导入失败都视为不可用
            sys.modules[name] = None
            disabled.append(name)
            LOGGER.warning(
                "可选依赖 %s 导入失败（%s），已在进程内标记为不可用", name, type(exc).__name__
            )
    return disabled


def _read_prompts(model_dir: Path) -> tuple[str, str]:
    """读取模型 ``config_sentence_transformers.json`` 的 query/document 前缀。"""
    path = model_dir / "config_sentence_transformers.json"
    try:
        with path.open(encoding="utf-8") as stream:
            prompts = json.load(stream).get("prompts") or {}
    except (OSError, ValueError) as exc:
        LOGGER.warning("读取 %s 失败（%s），查询前缀回退为内置常量", path, type(exc).__name__)
        return QUERY_INSTRUCTION_FALLBACK, ""
    query = prompts.get("query") or QUERY_INSTRUCTION_FALLBACK
    document = prompts.get("document") or ""
    return str(query), str(document)


class LocalEmbedder:
    """Qwen3-Embedding-0.6B 的加载、批推理、池化与归一化封装（线程安全）。"""

    def __init__(
        self,
        model_dir: Path | str = DEFAULT_MODEL_DIR,
        *,
        device: str = "auto",
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_length: int = DEFAULT_MAX_LENGTH,
        dim: int = EMBEDDING_DIM,
    ) -> None:
        self.model_dir = Path(model_dir).expanduser().resolve()
        self.model_name = self.model_dir.name or DEFAULT_MODEL_NAME
        self.requested_device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self.dim = dim
        self.device = "unknown"
        self.dtype_name = "unknown"
        self.query_prefix, self.document_prefix = _read_prompts(self.model_dir)

        self._torch: Any = None
        self._tokenizer: Any = None
        self._model: Any = None
        self._lock = threading.Lock()
        self._ready = False
        self.error: dict[str, str] | None = None
        self.load_seconds: float | None = None
        self.loaded_at: str | None = None

    # -- 生命周期 --

    @property
    def ready(self) -> bool:
        return self._ready

    def load(self) -> bool:
        """加载模型；失败只记录错误并返回 False（进程保持存活，health 报 503）。"""
        started = time.perf_counter()
        try:
            self._load_or_raise()
        except Exception as exc:  # noqa: BLE001 —— 加载失败必须以结构化错误上报
            self._ready = False
            self.error = {
                "type": type(exc).__name__,
                "message": str(exc)[:500] or "模型加载失败（无更多信息）",
                "model_path": str(self.model_dir),
            }
            LOGGER.error("模型加载失败：%s: %s", type(exc).__name__, exc)
            return False

        self._ready = True
        self.error = None
        self.load_seconds = round(time.perf_counter() - started, 2)
        self.loaded_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        LOGGER.info(
            "模型就绪：path=%s device=%s dtype=%s dim=%d max_length=%d "
            "batch_size=%d query_prefix=%r 加载耗时=%.2fs",
            self.model_dir,
            self.device,
            self.dtype_name,
            self.dim,
            self.max_length,
            self.batch_size,
            self.query_prefix,
            self.load_seconds,
        )
        return True

    def _load_or_raise(self) -> None:
        if not self.model_dir.is_dir():
            raise FileNotFoundError(f"模型目录不存在：{self.model_dir}")

        disabled = _disable_broken_optional_deps()
        if disabled:
            LOGGER.info("已屏蔽不可用的可选依赖：%s", ", ".join(disabled))

        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

        import torch  # 延迟导入：无 torch 环境下模块仍可被导入（便于单测 HTTP 层）
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        logging.getLogger("transformers").setLevel(logging.ERROR)
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

        self.device = self._resolve_device(torch)
        dtype = torch.bfloat16 if self.device == "mps" else torch.float32
        self.dtype_name = str(dtype).replace("torch.", "")

        self._tokenizer = AutoTokenizer.from_pretrained(
            str(self.model_dir), local_files_only=True, trust_remote_code=False
        )
        self._tokenizer.padding_side = "right"  # last-token 池化配合 right padding
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        try:
            model = AutoModel.from_pretrained(
                str(self.model_dir),
                local_files_only=True,
                trust_remote_code=False,
                dtype=dtype,
            )
        except TypeError:
            # transformers < 5 用 torch_dtype（本项目环境为 5.x，仅作兼容）
            model = AutoModel.from_pretrained(
                str(self.model_dir),
                local_files_only=True,
                trust_remote_code=False,
                torch_dtype=dtype,
            )
        self._model = model.to(self.device).eval()

        hidden_size = int(getattr(self._model.config, "hidden_size", 0))
        if hidden_size != self.dim:
            raise RuntimeError(f"模型 hidden_size={hidden_size} 与约定维度 {self.dim} 不一致")

    def _resolve_device(self, torch: Any) -> str:
        requested = (self.requested_device or "auto").lower()
        if requested == "auto":
            return "mps" if torch.backends.mps.is_available() else "cpu"
        if requested == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("指定 --device mps，但当前环境 MPS 不可用")
        if requested not in ("cpu", "mps"):
            raise RuntimeError(f"不支持的 device：{self.requested_device}（可选 auto/cpu/mps）")
        return requested

    # -- 对外接口 --

    def health(self) -> dict[str, Any]:
        """``GET /health`` 的响应体；加载失败时附带结构化 error（HTTP 503）。"""
        body: dict[str, Any] = {
            "status": "ok" if self._ready else "error",
            "model": self.model_name,
            "dim": self.dim,
            "device": self.device,
            "model_path": str(self.model_dir),
            "backend": "transformers",
        }
        if self._ready:
            body["load_seconds"] = self.load_seconds
            body["loaded_at"] = self.loaded_at
        else:
            body["error"] = self.error or {
                "type": "ModelNotLoaded",
                "message": "模型尚未加载",
                "model_path": str(self.model_dir),
            }
        return body

    def embed(self, texts: list[str], input_type: str = "document") -> EmbeddingResult:
        """批量向量化：右侧 padding + attention_mask 定位末 token + L2 归一化。"""
        if not self._ready:
            message = "模型未就绪"
            if self.error:
                message = f"{message}：{self.error['type']}: {self.error['message']}"
            raise EmbeddingUnavailable(message)

        prefix = self.query_prefix if input_type == "query" else self.document_prefix
        prepared = [f"{prefix}{text}" for text in texts]

        with self._lock:  # MPS 上并发推理会争抢显存/命令队列，串行化最稳
            vectors, prompt_tokens = self._run_batches(prepared)

        for index, vector in enumerate(vectors):
            if len(vector) != self.dim:  # 契约硬约束：必须 1024 维
                raise RuntimeError(f"第 {index} 条向量维度为 {len(vector)}，应为 {self.dim}")
        return EmbeddingResult(vectors=vectors, prompt_tokens=prompt_tokens)

    def _run_batches(self, prepared: list[str]) -> tuple[list[list[float]], int]:
        torch = self._torch
        vectors: list[list[float]] = []
        prompt_tokens = 0

        with torch.inference_mode():
            for start in range(0, len(prepared), self.batch_size):
                batch = prepared[start : start + self.batch_size]
                encoded = self._tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                output = self._model(**encoded)

                hidden = getattr(output, "last_hidden_state", None)
                if hidden is None:  # 兼容只返回 hidden_states 的实现
                    hidden = output.hidden_states[-1]
                if hidden.shape[-1] != self.dim:
                    raise RuntimeError(
                        f"模型输出维度 {hidden.shape[-1]} 与约定维度 {self.dim} 不一致"
                    )

                attention_mask = encoded["attention_mask"]
                # 右侧 padding：每个样本有效 token 数 - 1 即其最后一个有效 token 下标
                last_indices = attention_mask.sum(dim=1) - 1
                rows = torch.arange(hidden.shape[0], device=hidden.device)
                pooled = hidden[rows, last_indices].to(torch.float32)
                normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)

                vectors.extend(normalized.detach().to("cpu").tolist())
                prompt_tokens += int(attention_mask.sum().item())

        return vectors, prompt_tokens


# --------------------------------------------------------------------------
# HTTP 层（仅标准库）
# --------------------------------------------------------------------------


class EmbeddingHTTPServer(ThreadingHTTPServer):
    """携带 embedder 的 HTTP 服务（embedder 可注入替身，便于端到端与单测）。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], embedder: Any):
        super().__init__(address, EmbeddingHTTPHandler)
        self.embedder = embedder


class EmbeddingHTTPHandler(BaseHTTPRequestHandler):
    server_version = "LocalEmbeddingSidecar/1.0"
    protocol_version = "HTTP/1.1"

    # -- 工具 --

    @property
    def embedder(self) -> Any:
        return self.server.embedder  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 —— 覆写基类签名
        LOGGER.debug("%s - %s", self.address_string(), format % args)

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error_body(
        self, status: int, message: str, *, param: str | None = None, code: str = "invalid_request"
    ) -> None:
        self._send_json(
            status,
            {
                "error": {
                    "message": message,
                    "type": "invalid_request_error",
                    "param": param,
                    "code": code,
                }
            },
        )

    def _read_body_bytes(self) -> bytes:
        """按 Content-Length 读完请求体；失败时调用方负责关闭连接。"""
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise EmbeddingRequestError("缺少 Content-Length")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise EmbeddingRequestError("Content-Length 非法") from exc
        if length <= 0:
            raise EmbeddingRequestError("请求体为空")
        if length > MAX_REQUEST_BYTES:
            raise EmbeddingRequestError(
                f"请求体超过上限 {MAX_REQUEST_BYTES} 字节", code="request_too_large"
            )
        return self.rfile.read(length)

    @staticmethod
    def _parse_json(raw: bytes) -> Any:
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EmbeddingRequestError("请求体不是合法 JSON") from exc

    # -- 路由 --

    def do_GET(self) -> None:  # noqa: N802 —— BaseHTTPRequestHandler 约定
        path = urlsplit(self.path).path
        if path == "/health":
            embedder = self.embedder
            body = embedder.health()
            status = 200 if body.get("status") == "ok" else 503
            self._send_json(status, body)
            return
        if path in ("/v1/embeddings", "/v1/models"):
            self._send_error_body(405, f"{path} 只接受 POST", code="method_not_allowed")
            return
        self._send_error_body(404, f"未知路径：{path}", code="not_found")

    def do_POST(self) -> None:  # noqa: N802 —— BaseHTTPRequestHandler 约定
        path = urlsplit(self.path).path
        if path == "/health":
            self._send_error_body(405, "/health 只接受 GET", code="method_not_allowed")
            return
        if path != "/v1/embeddings":
            self._send_error_body(404, f"未知路径：{path}", code="not_found")
            return
        self._handle_embeddings()

    def _handle_embeddings(self) -> None:
        started = time.perf_counter()
        embedder = self.embedder
        request: EmbeddingRequest | None = None
        try:
            raw = self._read_body_bytes()
            request = parse_embedding_request(self._parse_json(raw))
            result = embedder.embed(request.texts, request.input_type)
        except EmbeddingRequestError as exc:
            # 请求体可能未被完整消费，关闭连接避免 keep-alive 串包
            self.close_connection = True
            LOGGER.warning("embeddings 请求非法：%s", exc.message)
            self._send_error_body(400, exc.message, param=exc.param, code=exc.code)
            return
        except EmbeddingUnavailable as exc:
            LOGGER.error("embeddings 不可用：%s", exc)
            self._send_error_body(503, str(exc), code="model_unavailable")
            return
        except Exception as exc:  # noqa: BLE001 —— 推理异常也必须结构化返回
            LOGGER.exception("embeddings 推理失败")
            self._send_error_body(500, f"{type(exc).__name__}: {exc}", code="internal_error")
            return

        assert request is not None  # 只有成功解析的请求才会走到这里
        body = {
            "object": "list",
            "data": [
                {"object": "embedding", "index": index, "embedding": vector}
                for index, vector in enumerate(result.vectors)
            ],
            "model": embedder.model_name,
            "usage": {
                "prompt_tokens": result.prompt_tokens,
                "total_tokens": result.prompt_tokens,
            },
        }
        elapsed = time.perf_counter() - started
        self._send_json(200, body)
        LOGGER.info(
            "embeddings ok: n=%d input_type=%s dim=%d tokens=%d 耗时=%.3fs",
            len(request.texts),
            request.input_type,
            embedder.dim,
            result.prompt_tokens,
            elapsed,
        )


# --------------------------------------------------------------------------
# 启动入口
# --------------------------------------------------------------------------


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value in (None, "") else value


def resolve_model_dir(explicit: str | Path | None = None) -> Path:
    """解析模型目录：显式传入优先，其次按候选顺序取第一个存在的目录。

    worktree 检出时模型目录被 gitignore 忽略、只存在于主仓根，因此不能只认
    检出根平级那一个位置；都找不到时返回首选路径（加载时给出清晰报错）。
    """
    if explicit:
        return Path(explicit).expanduser()
    for candidate in MODEL_DIR_CANDIDATES:
        if candidate.is_dir():
            return candidate
    return DEFAULT_MODEL_DIR


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """命令行参数；优先级：CLI > 环境变量 > 内置默认。"""
    parser = argparse.ArgumentParser(
        description="本地 Qwen3-Embedding-0.6B 侧车（OpenAI 兼容 /v1/embeddings）"
    )
    parser.add_argument(
        "--model-dir",
        default=_env("LOCAL_EMBEDDING_MODEL_DIR", "") or None,
        help=(
            "模型本地目录（默认按顺序探测：检出根平级 → 主仓根 → 家目录，"
            f"常见位置 {DEFAULT_MODEL_DIR}）"
        ),
    )
    parser.add_argument("--host", default=_env("LOCAL_EMBEDDING_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port", type=int, default=int(_env("LOCAL_EMBEDDING_PORT", str(DEFAULT_PORT)))
    )
    parser.add_argument(
        "--device",
        default=_env("LOCAL_EMBEDDING_DEVICE", "auto"),
        choices=["auto", "cpu", "mps"],
        help="推理设备（默认 auto：MPS 可用则 mps+bfloat16，否则 cpu+float32）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(_env("LOCAL_EMBEDDING_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))),
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=int(_env("LOCAL_EMBEDDING_MAX_LENGTH", str(DEFAULT_MAX_LENGTH))),
    )
    parser.add_argument(
        "--log-level", default=_env("LOCAL_EMBEDDING_LOG_LEVEL", "INFO"), help="DEBUG/INFO/WARNING"
    )
    return parser.parse_args(argv)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_level)

    model_dir = resolve_model_dir(args.model_dir)
    LOGGER.info("启动本地 Embedding 侧车：model_dir=%s device=%s", model_dir, args.device)
    embedder = LocalEmbedder(
        model_dir,
        device=args.device,
        batch_size=args.batch_size,
        max_length=args.max_length,
    )
    if not embedder.load():
        LOGGER.error(
            "模型加载失败，服务仍将启动：/health 返回 503，/v1/embeddings 返回 503。"
            " 请修复依赖或模型路径后重启。"
        )

    server = EmbeddingHTTPServer((args.host, args.port), embedder)
    host, port = server.server_address[0], server.server_address[1]
    LOGGER.info(
        "监听 http://%s:%s （health: GET /health, embeddings: POST /v1/embeddings）", host, port
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("收到中断信号，正在退出")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

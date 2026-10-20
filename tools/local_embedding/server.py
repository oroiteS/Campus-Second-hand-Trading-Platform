"""本地 Embedding 侧车服务（OpenAI 兼容）——加载本机 Qwen3-Embedding-0.6B。

设计要点（详见同目录 README.md）：

- 运行在独立的 ``~/my/torch_python/.venv``（torch + transformers）环境，与
  Flask 后端（无 torch）运行时不同，因此独立成 ``tools/local_embedding/``，
  不放进 ``campus_backend/src/``；后端只经 HTTP 调用本服务。
- 仅用标准库 ``http.server`` 实现 HTTP 层，不引入 Flask 等额外依赖。
- ``POST /v1/embeddings`` 兼容 OpenAI 语义（``input`` 为字符串或字符串数组），
  额外支持非标准字段 ``input_type``（query / document）选择是否加查询指令前缀；
  ``GET /v1/models`` 返回 OpenAI 格式的单模型列表。
- 池化按模型自身配置：last-token pooling（用 attention_mask 定位最后一个有效
  token）+ L2 归一化，输出固定 1024 维（与后端 ``EMBEDDING_DIM`` 一致）。
- 启动时跑一次 **推理内核自检**（SDPA causal，生产 dtype/device vs CPU fp32
  基准），结果写入 ``GET /health`` 的 ``selftest`` 字段，防内核回归导致的
  “探活正常、向量全错”。
- 模型加载失败时进程不退出：``GET /health`` 返回 503 且带结构化错误。
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
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


def _shield_broken_optional_deps() -> list[str]:
    """屏蔽「装了但导入即失败」的可选依赖，避免拖垮 ``import transformers``。

    背景（实测）：``transformers`` 5.20.x 在 **模块导入期** 就无条件执行
    ``from sklearn.metrics import roc_curve``（``generation/candidate_generator``）
    与 ``from scipy.optimize import linear_sum_assignment``
    （``loss/loss_for_object_detection``）；两处都用 ``is_*_available()`` 守卫，
    而该守卫走 ``importlib.util.find_spec(name)``。因此只要包“存在但导入失败”
    （如历史环境里 scipy 的 ``_propack`` 动态库损坏），transformers 导入就会崩，
    而 ``find_spec`` 探测本身不报错。

    策略（P1-1：最小化屏蔽粒度）：

    1. **探测 transformers 真正需要的那一句 import**，而不是 ``import scipy``
       这种粗粒度探测——只要 ``scipy.linalg`` 之类的其它子模块坏了、而
       ``scipy.optimize.linear_sum_assignment`` 可用，就不会误伤 scipy；
    2. 只在探测失败时，把**该包**在 ``sys.modules`` 里置 ``None``：
       ``find_spec`` 随即返回 ``None``，transformers 跳过对应 import；
    3. ``sklearn`` 与 ``scipy`` 各自独立判断，互不牵连；
    4. 包不存在（未安装）时无需处理——``find_spec`` 本来就是 ``None``。

    侧车推理根本不需要 scipy / sklearn，屏蔽对功能无影响；包修好后本函数
    自动变成 no-op。
    """
    shielded: list[str] = []
    # (包名, transformers 实际会 import 的子模块, 需要的符号, 说明)
    probes = (
        ("sklearn", "sklearn.metrics", "roc_curve", "候选生成器"),
        ("scipy", "scipy.optimize", "linear_sum_assignment", "目标检测损失"),
    )
    for name, module_name, symbol, purpose in probes:
        if importlib.util.find_spec(name) is None:
            LOGGER.debug("可选依赖 %s 未安装，transformers 会自动跳过（%s）", name, purpose)
            continue
        try:
            getattr(importlib.import_module(module_name), symbol)
        except Exception as exc:  # noqa: BLE001 —— 任何导入失败都视为不可用
            sys.modules[name] = None
            shielded.append(name)
            LOGGER.warning(
                "可选依赖 %s 存在但不可用（%s: %s），已在进程内标记为不可用；"
                "transformers 将跳过依赖它的 %s 功能（侧车推理不受影响）",
                name,
                type(exc).__name__,
                str(exc)[:200],
                purpose,
            )
    return shielded


# --------------------------------------------------------------------------
# 推理内核自检（防 torch / MPS / SDPA 内核回归）
# --------------------------------------------------------------------------

# 自检序列长度：覆盖长序列路径（历史上 MPS SDPA 在 seq>16 才走分块/长序列
# 分支），且足够短（毫秒级）不拖慢启动。
SELFTEST_SEQ_LENS = (17, 24, 32)
# 自检通过的相对误差阈值；正确实现应 ≲0.01（bf16 舍入），内核 bug 时可达 1e+0。
SELFTEST_MAX_REL_ERR = 0.05
SELFTEST_HEADS = 4
# 必须与真实模型 config 的 head_dim 一致（Qwen3-Embedding-0.6B: head_dim=128）。
# 实测 torch 2.14.1 的 MPS bf16 SDPA 在 head_dim ∈ {8,16} 且 seq>16 时仍给出
# 错误结果（rel_err≈1.18），但 head_dim=32/64/128/256 正常；本模型走 128，
# 因此自检用真实 head_dim，避免把无关的内核缺口当成生产故障误报。
SELFTEST_HEAD_DIM = 128


def _reference_causal_attention(torch: Any, q: Any, k: Any, v: Any) -> Any:
    """独立基准：用 matmul + 显式 causal mask + softmax 手算注意力。

    刻意**不走** ``F.scaled_dot_product_attention``——自检要和被测内核比对，
    基准与被测不能是同一个实现（否则内核坏了两边一起错，差值恒为 0）。
    """
    scale = q.shape[-1] ** -0.5
    scores = torch.matmul(q, k.transpose(-1, -2)) * scale
    seq = q.shape[-2]
    mask = torch.tril(torch.ones(seq, seq, dtype=torch.bool, device=q.device))
    scores = scores.masked_fill(~mask, float("-inf"))
    return torch.matmul(torch.softmax(scores, dim=-1), v)


def run_kernel_selftest(torch: Any, device: str, dtype: Any) -> dict[str, Any]:
    """对比生产配置（device+dtype，SDPA causal）与独立 CPU fp32 基准的输出。

    对 ``SELFTEST_SEQ_LENS`` 每个长度：固定种子生成 Q/K/V（head_dim 与真实
    模型一致），分别在
      (a) 生产配置（如 mps+bfloat16）上走 ``F.scaled_dot_product_attention``；
      (b) CPU fp32 上手算 causal attention（``_reference_causal_attention``）
    再回到 CPU fp32 比较相对误差，取各长度最大值。

    这样任何「设备 / 精度 / 内核」回归都能在启动时暴露，而不是等向量全错
    （历史教训：探活永远正常，实际向量全错）。

    只依赖 ``torch``，不加载模型，毫秒级；失败不抛异常，返回结构化结果。
    """
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "status": "skipped",
        "seq_lens": list(SELFTEST_SEQ_LENS),
        "head_dim": SELFTEST_HEAD_DIM,
        "device": device,
        "dtype": str(dtype).replace("torch.", ""),
        "max_rel_err": None,
        "per_seq": results,
        "threshold": SELFTEST_MAX_REL_ERR,
    }
    try:
        for seq_len in SELFTEST_SEQ_LENS:
            torch.manual_seed(20261020)
            shape = (1, SELFTEST_HEADS, seq_len, SELFTEST_HEAD_DIM)
            q_cpu = torch.randn(*shape, dtype=torch.float32)
            k_cpu = torch.randn(*shape, dtype=torch.float32)
            v_cpu = torch.randn(*shape, dtype=torch.float32)

            expected = _reference_causal_attention(torch, q_cpu, k_cpu, v_cpu)

            produced = torch.nn.functional.scaled_dot_product_attention(
                q_cpu.to(device=device, dtype=dtype),
                k_cpu.to(device=device, dtype=dtype),
                v_cpu.to(device=device, dtype=dtype),
                is_causal=True,
            )
            if device == "mps":
                torch.mps.synchronize()
            produced_cpu = produced.to(device="cpu", dtype=torch.float32)

            diff = (produced_cpu - expected).abs().max().item()
            scale = expected.abs().max().item() or 1.0
            rel_err = diff / scale
            results.append({"seq_len": seq_len, "rel_err": round(rel_err, 6)})

        worst = max(item["rel_err"] for item in results)
        result["max_rel_err"] = round(worst, 6)
        result["status"] = "ok" if worst <= SELFTEST_MAX_REL_ERR else "failed"
    except Exception as exc:  # noqa: BLE001 —— 自检失败不能影响服务
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]

    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    if result["status"] == "ok":
        LOGGER.info(
            "推理内核自检通过：device=%s dtype=%s seq=%s head_dim=%d max_rel_err=%.6f 耗时=%.1fms",
            result["device"],
            result["dtype"],
            "/".join(str(item["seq_len"]) for item in results),
            result["head_dim"],
            result["max_rel_err"],
            result["elapsed_ms"],
        )
    elif result["status"] == "failed":
        LOGGER.error(
            "推理内核自检失败：device=%s dtype=%s head_dim=%d max_rel_err=%s（逐长度 %s）"
            " 超过阈值 %.3f。该设备/精度组合的注意力内核可能有问题，向量结果不可信；"
            " 请尝试 --device cpu 或改回 float32 后复测。",
            result["device"],
            result["dtype"],
            result["head_dim"],
            result["max_rel_err"],
            ", ".join(f"seq{item['seq_len']}={item['rel_err']}" for item in results),
            SELFTEST_MAX_REL_ERR,
        )
    else:
        LOGGER.error("推理内核自检异常：%s", result.get("error"))
    return result


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
        self._dtype: Any = None
        self.query_prefix, self.document_prefix = _read_prompts(self.model_dir)

        self._torch: Any = None
        self._tokenizer: Any = None
        self._model: Any = None
        self._lock = threading.Lock()
        self._ready = False
        self.error: dict[str, str] | None = None
        self.load_seconds: float | None = None
        self.loaded_at: str | None = None
        # 推理内核自检结果（启动时算一次，随 /health 暴露，不阻止服务启动）
        self.selftest: dict[str, Any] | None = None

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
        self.selftest = run_kernel_selftest(self._torch, self.device, self._dtype)
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

        shielded = _shield_broken_optional_deps()
        if shielded:
            LOGGER.info("已屏蔽不可用的可选依赖：%s", ", ".join(shielded))

        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

        import torch  # 延迟导入：无 torch 环境下模块仍可被导入（便于单测 HTTP 层）
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        logging.getLogger("transformers").setLevel(logging.ERROR)
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

        self.device = self._resolve_device(torch)
        dtype = torch.bfloat16 if self.device == "mps" else torch.float32
        self._dtype = dtype
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
        """``GET /health`` 的响应体；加载失败时附带结构化 error（HTTP 503）。

        ``selftest`` 为启动时推理内核自检的结论：``ok`` / ``failed`` / ``error``
        / ``skipped``。``failed`` 时 /health 仍返回 200（服务可用但结果可疑），
        由该字段与 ERROR 日志显著暴露问题。
        """
        body: dict[str, Any] = {
            "status": "ok" if self._ready else "error",
            "model": self.model_name,
            "dim": self.dim,
            "device": self.device,
            "model_path": str(self.model_dir),
            "backend": "transformers",
            "selftest": self.selftest["status"] if self.selftest else "skipped",
        }
        if self._ready:
            body["dtype"] = self.dtype_name
            body["load_seconds"] = self.load_seconds
            body["loaded_at"] = self.loaded_at
            if self.selftest:
                body["selftest_detail"] = self.selftest
        else:
            body["error"] = self.error or {
                "type": "ModelNotLoaded",
                "message": "模型尚未加载",
                "model_path": str(self.model_dir),
            }
        return body

    def models(self) -> dict[str, Any]:
        """``GET /v1/models`` 的响应体（OpenAI 格式，供客户端/LangChain 探测）。"""
        return {
            "object": "list",
            "data": [
                {
                    "id": self.model_name,
                    "object": "model",
                    "created": 0,
                    "owned_by": "local",
                }
            ],
        }

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
        self,
        status: int,
        message: str,
        *,
        param: str | None = None,
        code: str = "invalid_request",
        error_type: str = "invalid_request_error",
    ) -> None:
        """发送错误响应。

        **一律关闭连接**：非 200 分支通常没有消费请求体（未知路径 / 方法不符
        / 提前拒绝），keep-alive 复用同连接时残留 body 会被当成下一个请求行，
        造成 400/501 串包（P2-1 实测：POST /nope 后同连接 GET /health 得到
        501 与残缺 HTML）。错误响应本身就是例外路径，断开连接代价可忽略。
        """
        self.close_connection = True
        self._send_json(
            status,
            {
                "error": {
                    "message": message,
                    "type": error_type,
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
            if status != 200:
                self.close_connection = True
            return
        if path == "/v1/models":
            # OpenAI 语义：GET /v1/models 列模型（客户端与 LangChain 常探测）
            self._send_json(200, self.embedder.models())
            return
        if path == "/v1/embeddings":
            self._send_error_body(405, "/v1/embeddings 只接受 POST", code="method_not_allowed")
            return
        self._send_error_body(404, f"未知路径：{path}", code="not_found")

    def do_POST(self) -> None:  # noqa: N802 —— BaseHTTPRequestHandler 约定
        path = urlsplit(self.path).path
        if path == "/health":
            self._send_error_body(405, "/health 只接受 GET", code="method_not_allowed")
            return
        if path == "/v1/models":
            self._send_error_body(405, "/v1/models 只接受 GET", code="method_not_allowed")
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
            LOGGER.warning("embeddings 请求非法：%s", exc.message)
            self._send_error_body(400, exc.message, param=exc.param, code=exc.code)
            return
        except EmbeddingUnavailable as exc:
            LOGGER.error("embeddings 不可用：%s", exc)
            self._send_error_body(
                503, str(exc), code="model_unavailable", error_type="service_unavailable"
            )
            return
        except Exception as exc:  # noqa: BLE001 —— 推理异常也必须结构化返回
            LOGGER.exception("embeddings 推理失败")
            self._send_error_body(
                500,
                f"{type(exc).__name__}: {exc}",
                code="internal_error",
                error_type="server_error",
            )
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

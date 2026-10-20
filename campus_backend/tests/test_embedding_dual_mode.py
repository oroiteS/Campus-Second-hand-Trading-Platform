"""Embedding 双模探活（云端优先、本地兜底）的 service 层用例。

探针可整体注入的机制不变：这组用例直接替换 ``_embedding_ping``，从而在
不起真实网络的前提下覆盖云端 / 本地 / 都失败 / 本地被禁用四条分支，并
断言契约 EmbeddingHealth 的 mode/model/dim/status 四字段映射。
"""

import pytest

from src.config import Config
from src.services import system_service
from src.services.system_service import HealthProbes, _embedding_health


class _DualModeConfig(Config):
    """测试配置：显式写死双模参数，避免受开发者本地 .env 影响。"""

    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    EMBEDDING_BASE_URL = "https://cloud.invalid/v1"
    EMBEDDING_API_KEY = "cloud-key"
    EMBEDDING_MODEL = "cloud-model"
    EMBEDDING_DIM = 1024
    EMBEDDING_LOCAL_BASE_URL = "http://127.0.0.1:8010/v1"
    EMBEDDING_LOCAL_MODEL = "qwen3_embedding_0_6b"
    EMBEDDING_LOCAL_ENABLED = True


@pytest.fixture()
def dual_app():
    from src.app import create_app

    return create_app(_DualModeConfig)


@pytest.fixture()
def dual_client(dual_app):
    return dual_app.test_client()


class _StubPing:
    """可编程的 ``_embedding_ping`` 替身：按 base_url 决定成功或抛错。"""

    def __init__(self, failing_urls=(), error: Exception | None = None):
        self.failing_urls = set(failing_urls)
        self.error = error or ConnectionError("Connection refused")
        self.calls: list[dict] = []

    def __call__(self, base_url: str, api_key: str, model: str, timeout_s: float) -> None:
        self.calls.append(
            {"base_url": base_url, "api_key": api_key, "model": model, "timeout_s": timeout_s}
        )
        if base_url in self.failing_urls:
            raise self.error


def _health(
    app,
    *,
    cloud_ok: bool,
    local_ok: bool,
    local_enabled: bool = True,
    local_url: str | None = None,
    local_model: str | None = None,
) -> dict:
    """在应用上下文中调用 _embedding_health，云端/本地可用性由参数控制。"""
    failing = []
    if not cloud_ok:
        failing.append(_DualModeConfig.EMBEDDING_BASE_URL)
    if not local_ok:
        failing.append(local_url or _DualModeConfig.EMBEDDING_LOCAL_BASE_URL)
    stub = _StubPing(failing_urls=failing)
    with app.app_context():
        original = system_service._embedding_ping
        system_service._embedding_ping = stub
        try:
            result = _embedding_health(
                cloud_base_url=_DualModeConfig.EMBEDDING_BASE_URL,
                cloud_api_key=_DualModeConfig.EMBEDDING_API_KEY,
                cloud_model=_DualModeConfig.EMBEDDING_MODEL,
                dim=_DualModeConfig.EMBEDDING_DIM,
                local_base_url=local_url
                if local_url is not None
                else _DualModeConfig.EMBEDDING_LOCAL_BASE_URL,
                local_model=local_model
                if local_model is not None
                else _DualModeConfig.EMBEDDING_LOCAL_MODEL,
                local_enabled=local_enabled,
            )
        finally:
            system_service._embedding_ping = original
    return {"result": result, "calls": stub.calls}


class TestDualModeMapping:
    """四条分支的契约映射（关键用例：云端失败 + 本地成功 → mode=local）。"""

    def test_cloud_up_reports_cloud_and_skips_local(self, dual_app):
        out = _health(dual_app, cloud_ok=True, local_ok=True)
        assert out["result"] == {
            "mode": "cloud",
            "model": _DualModeConfig.EMBEDDING_MODEL,
            "dim": 1024,
            "status": "up",
        }
        # 云端可用时不应触碰本地侧车
        assert [call["base_url"] for call in out["calls"]] == [_DualModeConfig.EMBEDDING_BASE_URL]
        assert out["calls"][0]["timeout_s"] == system_service._EMBEDDING_TIMEOUT_S == 5.0

    def test_cloud_down_local_up_reports_local(self, dual_app):
        out = _health(dual_app, cloud_ok=False, local_ok=True)
        assert out["result"] == {
            "mode": "local",
            "model": _DualModeConfig.EMBEDDING_LOCAL_MODEL,
            "dim": 1024,
            "status": "up",
        }
        assert [call["base_url"] for call in out["calls"]] == [
            _DualModeConfig.EMBEDDING_BASE_URL,
            _DualModeConfig.EMBEDDING_LOCAL_BASE_URL,
        ]
        assert out["calls"][1]["model"] == _DualModeConfig.EMBEDDING_LOCAL_MODEL

    def test_both_down_reports_null_mode(self, dual_app):
        out = _health(dual_app, cloud_ok=False, local_ok=False)
        assert out["result"] == {
            "mode": None,
            "model": _DualModeConfig.EMBEDDING_MODEL,
            "dim": 1024,
            "status": "down",
        }
        assert len(out["calls"]) == 2

    def test_local_disabled_short_circuits_to_down(self, dual_app):
        out = _health(dual_app, cloud_ok=False, local_ok=True, local_enabled=False)
        assert out["result"] == {
            "mode": None,
            "model": _DualModeConfig.EMBEDDING_MODEL,
            "dim": 1024,
            "status": "down",
        }
        # 禁用后不得再探测本地
        assert [call["base_url"] for call in out["calls"]] == [_DualModeConfig.EMBEDDING_BASE_URL]

    def test_missing_local_config_treated_as_down(self, dual_app):
        out = _health(dual_app, cloud_ok=False, local_ok=True, local_url="", local_model="")
        assert out["result"]["mode"] is None
        assert out["result"]["status"] == "down"

    def test_cloud_failure_is_logged_without_secret(self, dual_app, caplog):
        secret = _DualModeConfig.EMBEDDING_API_KEY
        with caplog.at_level("WARNING"):
            _health(dual_app, cloud_ok=False, local_ok=True)
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "云端不可用" in messages
        assert secret not in messages


class TestDualModeEndpointAggregation:
    """聚合层：Embedding 降级不得改变 HTTP 语义（契约：仍 200）。"""

    @staticmethod
    def _up(latency_ms: int = 1):
        return lambda: {"status": "up", "latency_ms": latency_ms, "error": None}

    def _probes(self, embedding) -> HealthProbes:
        return HealthProbes(
            mysql=self._up(),
            mongodb=self._up(),
            redis=self._up(),
            chroma=self._up(),
            embedding=embedding,
        )

    def test_local_mode_aggregates_ok_when_other_deps_up(self, dual_app):
        local_up = {
            "mode": "local",
            "model": "qwen3_embedding_0_6b",
            "dim": 1024,
            "status": "up",
        }
        with dual_app.app_context():
            data = system_service.check_health(self._probes(lambda: local_up))
        assert data["status"] == "ok"
        assert data["embedding"] == local_up

    def test_local_endpoint_via_http_still_200(self, dual_client, monkeypatch):
        probes = self._probes(
            lambda: {
                "mode": "local",
                "model": "qwen3_embedding_0_6b",
                "dim": 1024,
                "status": "up",
            }
        )
        monkeypatch.setattr(system_service, "build_default_probes", lambda: probes)
        res = dual_client.get("/api/health")
        assert res.status_code == 200
        body = res.get_json()
        assert body["code"] == 0
        assert body["data"]["status"] == "ok"
        assert body["data"]["embedding"]["mode"] == "local"
        assert set(body["data"]["embedding"]) == {"mode", "model", "dim", "status"}

    def test_both_down_endpoint_degrades_but_200(self, dual_client, monkeypatch):
        probes = self._probes(
            lambda: {"mode": None, "model": "cloud-model", "dim": 1024, "status": "down"}
        )
        monkeypatch.setattr(system_service, "build_default_probes", lambda: probes)
        res = dual_client.get("/api/health")
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["status"] == "degraded"
        assert data["embedding"]["mode"] is None
        assert data["embedding"]["status"] == "down"


class TestDefaultProbesWiring:
    """配置 → 探针接线：三个 EMBEDDING_LOCAL_* 必须经 app.config 传入。"""

    def test_default_probe_uses_dual_mode_config(self, dual_app, monkeypatch):
        stub = _StubPing(failing_urls={_DualModeConfig.EMBEDDING_BASE_URL})
        monkeypatch.setattr(system_service, "_embedding_ping", stub)
        with dual_app.app_context():
            result = system_service.build_default_probes().embedding()
        assert result["mode"] == "local"
        assert result["model"] == _DualModeConfig.EMBEDDING_LOCAL_MODEL
        assert [call["base_url"] for call in stub.calls] == [
            _DualModeConfig.EMBEDDING_BASE_URL,
            _DualModeConfig.EMBEDDING_LOCAL_BASE_URL,
        ]

    def test_local_disabled_flag_respected(self, monkeypatch):
        from src.app import create_app

        class _Disabled(_DualModeConfig):
            EMBEDDING_LOCAL_ENABLED = False

        app = create_app(_Disabled)
        stub = _StubPing(failing_urls={_DualModeConfig.EMBEDDING_BASE_URL})
        monkeypatch.setattr(system_service, "_embedding_ping", stub)
        with app.app_context():
            result = system_service.build_default_probes().embedding()
        assert result["status"] == "down"
        assert result["mode"] is None
        assert len(stub.calls) == 1

    def test_config_defaults(self, monkeypatch):
        """配置默认值：本地侧车 8010 / 模型名 / 默认启用（无环境变量时）。"""
        from src import config as config_module

        for name in (
            "EMBEDDING_LOCAL_BASE_URL",
            "EMBEDDING_LOCAL_MODEL",
            "EMBEDDING_LOCAL_ENABLED",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(config_module, "_env_str", lambda key, default="": default)
        assert config_module._env_str("EMBEDDING_LOCAL_BASE_URL", "http://127.0.0.1:8010/v1") == (
            "http://127.0.0.1:8010/v1"
        )
        assert config_module._env_bool("EMBEDDING_LOCAL_ENABLED", True) is True
        assert config_module._env_bool("__not_set__", True) is True
        assert config_module._env_bool("__not_set__", False) is False
        assert config_module._env_str("EMBEDDING_LOCAL_MODEL", "qwen3_embedding_0_6b") == (
            "qwen3_embedding_0_6b"
        )

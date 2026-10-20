"""Embedding 探活（EMBEDDING_MODE = local | cloud | auto）的 service 层用例。

探针可整体注入的机制不变：这组用例直接替换 ``_embedding_ping``，从而在
不起真实网络的前提下覆盖三种模式的各条分支，并断言契约 EmbeddingHealth
的 mode/model/dim/status 四字段映射。

- ``local``（默认）：只探本地侧车，**零云端请求**；
- ``cloud``：只探云端，失败不回落本地；
- ``auto``：旧行为——云端优先、本地兜底。
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
    EMBEDDING_MODE = "auto"  # 旧用例覆盖 auto 三段逻辑；新模式用例显式传 mode
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
    mode: str,
    cloud_base_url: str | None = None,
    cloud_api_key: str | None = None,
    cloud_model: str | None = None,
) -> dict:
    """在应用上下文中调用 _embedding_health，云端/本地可用性由参数控制。"""
    cloud_base_url = (
        _DualModeConfig.EMBEDDING_BASE_URL if cloud_base_url is None else cloud_base_url
    )
    cloud_api_key = (
        _DualModeConfig.EMBEDDING_API_KEY if cloud_api_key is None else cloud_api_key
    )
    cloud_model = _DualModeConfig.EMBEDDING_MODEL if cloud_model is None else cloud_model
    failing = []
    if not cloud_ok:
        failing.append(cloud_base_url)
    if not local_ok:
        failing.append(local_url or _DualModeConfig.EMBEDDING_LOCAL_BASE_URL)
    stub = _StubPing(failing_urls=failing)
    with app.app_context():
        original = system_service._embedding_ping
        system_service._embedding_ping = stub
        try:
            result = _embedding_health(
                cloud_base_url=cloud_base_url,
                cloud_api_key=cloud_api_key,
                cloud_model=cloud_model,
                dim=_DualModeConfig.EMBEDDING_DIM,
                local_base_url=local_url
                if local_url is not None
                else _DualModeConfig.EMBEDDING_LOCAL_BASE_URL,
                local_model=local_model
                if local_model is not None
                else _DualModeConfig.EMBEDDING_LOCAL_MODEL,
                local_enabled=local_enabled,
                mode=mode,
            )
        finally:
            system_service._embedding_ping = original
    return {"result": result, "calls": stub.calls}


def _cloud_calls(calls: list[dict]) -> list[dict]:
    """过滤出云端探针调用（按 base_url 区分云端与本地侧车）。"""
    return [call for call in calls if call["base_url"] == _DualModeConfig.EMBEDDING_BASE_URL]


def _local_calls(calls: list[dict]) -> list[dict]:
    return [call for call in calls if call["base_url"] == _DualModeConfig.EMBEDDING_LOCAL_BASE_URL]


class TestDualModeMapping:
    """四条分支的契约映射（关键用例：云端失败 + 本地成功 → mode=local）。"""

    def test_cloud_up_reports_cloud_and_skips_local(self, dual_app):
        out = _health(dual_app, cloud_ok=True, local_ok=True, mode="auto")
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
        out = _health(dual_app, cloud_ok=False, local_ok=True, mode="auto")
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
        out = _health(dual_app, cloud_ok=False, local_ok=False, mode="auto")
        assert out["result"] == {
            "mode": None,
            "model": _DualModeConfig.EMBEDDING_MODEL,
            "dim": 1024,
            "status": "down",
        }
        assert len(out["calls"]) == 2

    def test_local_disabled_short_circuits_to_down(self, dual_app):
        out = _health(dual_app, cloud_ok=False, local_ok=True, local_enabled=False, mode="auto")
        assert out["result"] == {
            "mode": None,
            "model": _DualModeConfig.EMBEDDING_MODEL,
            "dim": 1024,
            "status": "down",
        }
        # 禁用后不得再探测本地
        assert [call["base_url"] for call in out["calls"]] == [_DualModeConfig.EMBEDDING_BASE_URL]

    def test_missing_local_config_treated_as_down(self, dual_app):
        out = _health(
            dual_app, cloud_ok=False, local_ok=True, local_url="", local_model="", mode="auto"
        )
        assert out["result"]["mode"] is None
        assert out["result"]["status"] == "down"

    def test_cloud_failure_is_logged_without_secret(self, dual_app, caplog):
        secret = _DualModeConfig.EMBEDDING_API_KEY
        with caplog.at_level("WARNING"):
            _health(dual_app, cloud_ok=False, local_ok=True, mode="auto")
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


class TestEmptyCloudConfigGuard:
    """P2-4：base_url / key / model 为空时必须短路，绝不外发请求。

    ``OpenAI(base_url="")`` 会隐式回落到官方 ``https://api.openai.com/v1``，
    若 api_key 非空则凭据外泄；因此这三条是安全用例，不能只测"不报错"。
    """

    @staticmethod
    def _run(app, **overrides):
        kwargs = {
            "cloud_base_url": _DualModeConfig.EMBEDDING_BASE_URL,
            "cloud_api_key": _DualModeConfig.EMBEDDING_API_KEY,
            "cloud_model": _DualModeConfig.EMBEDDING_MODEL,
            "dim": 1024,
            "local_base_url": "",
            "local_model": "",
            "local_enabled": False,
            "mode": "auto",  # 该组用例覆盖的是 auto 下的云端短路逻辑
        }
        kwargs.update(overrides)
        stub = _StubPing()
        with app.app_context():
            original = system_service._embedding_ping
            system_service._embedding_ping = stub
            try:
                result = _embedding_health(**kwargs)
            finally:
                system_service._embedding_ping = original
        return result, stub.calls

    @pytest.mark.parametrize(
        ("overrides", "missing"),
        [
            ({"cloud_base_url": ""}, "EMBEDDING_BASE_URL"),
            ({"cloud_base_url": "   "}, "EMBEDDING_BASE_URL"),
            ({"cloud_api_key": ""}, "EMBEDDING_API_KEY"),
            ({"cloud_model": ""}, "EMBEDDING_MODEL"),
        ],
    )
    def test_empty_cloud_config_sends_no_request(self, dual_app, caplog, overrides, missing):
        with caplog.at_level("WARNING"):
            result, calls = self._run(dual_app, **overrides)
        assert calls == [], "云端配置不全时不得发起任何请求（防 base_url 回落外发）"
        assert result["status"] == "down"
        assert result["mode"] is None
        assert result["model"] == overrides.get("cloud_model", _DualModeConfig.EMBEDDING_MODEL)
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert missing in messages
        # 报错只提变量名，绝不回显取值
        assert _DualModeConfig.EMBEDDING_API_KEY not in messages

    def test_ping_itself_refuses_empty_base_url(self):
        """第二道防线：即使绕过入口判空，``_embedding_ping`` 也不发请求。"""
        with pytest.raises(ValueError, match="未配置"):
            system_service._embedding_ping("", "some-key", "model", 1.0)

    def test_empty_cloud_falls_back_to_local_when_enabled(self, dual_app):
        result, calls = self._run(
            dual_app,
            cloud_base_url="",
            local_base_url="http://127.0.0.1:8010/v1",
            local_model="qwen3_embedding_0_6b",
            local_enabled=True,
        )
        assert result["mode"] == "local"
        assert [call["base_url"] for call in calls] == ["http://127.0.0.1:8010/v1"]


class TestInlineCommentTolerance:
    """P2-3：``.env`` 行内注释不得影响数值 / 布尔解析。"""

    def test_env_bool_strips_inline_comment(self, monkeypatch):
        from src import config as config_module

        cases = {
            "true # false=关闭本地兜底": True,
            "false   # 关闭": False,
            "TRUE#注释": True,
            "1 # on": True,
            "0 # off": False,
            "# 全是注释": True,  # 空值回退默认
        }
        for raw, expected in cases.items():
            monkeypatch.setenv("__B0BE2_BOOL__", raw)
            assert config_module._env_bool("__B0BE2_BOOL__", True) is expected, raw

    def test_env_int_strips_inline_comment(self, monkeypatch):
        from src import config as config_module

        cases = {"1024 # 维度": 1024, "8010 # 端口": 8010, "# 注释": 7, "abc": 7}
        for raw, expected in cases.items():
            monkeypatch.setenv("__B0BE2_INT__", raw)
            assert config_module._env_int("__B0BE2_INT__", 7) == expected, raw

    def test_env_str_keeps_hash_for_secrets(self, monkeypatch):
        """字符串型变量（密钥/密码）里的 ``#`` 必须原样保留，不能被当注释。"""
        from src import config as config_module

        monkeypatch.setenv("__B0BE2_STR__", "p#ss#word")
        assert config_module._env_str("__B0BE2_STR__") == "p#ss#word"


class TestLocalMode:
    """EMBEDDING_MODE=local（默认）：只打本地侧车，零云端请求。"""

    def test_local_up_reports_local_without_any_cloud_request(self, dual_app):
        out = _health(dual_app, cloud_ok=True, local_ok=True, mode="local")
        assert out["result"] == {
            "mode": "local",
            "model": _DualModeConfig.EMBEDDING_LOCAL_MODEL,
            "dim": 1024,
            "status": "up",
        }
        # 关键断言：本地可用时云端探针零调用（零外发、零 5s 等待）
        assert _cloud_calls(out["calls"]) == []
        assert [call["base_url"] for call in out["calls"]] == [
            _DualModeConfig.EMBEDDING_LOCAL_BASE_URL
        ]
        # 本地探活仍用 15s 超时，且不校验云端凭据
        assert out["calls"][0]["timeout_s"] == system_service._EMBEDDING_LOCAL_TIMEOUT_S == 15.0
        assert out["calls"][0]["api_key"] == "local"

    def test_local_down_reports_null_mode_and_local_model(self, dual_app, caplog):
        with caplog.at_level("WARNING"):
            out = _health(dual_app, cloud_ok=True, local_ok=False, mode="local")
        # 失败时 mode 必须是 null（不得报 cloud），model 报本地模型名
        assert out["result"] == {
            "mode": None,
            "model": _DualModeConfig.EMBEDDING_LOCAL_MODEL,
            "dim": 1024,
            "status": "down",
        }
        assert _cloud_calls(out["calls"]) == [], "local 模式失败也不得触碰云端"
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "本地侧车不可用" in messages
        assert _DualModeConfig.EMBEDDING_API_KEY not in messages

    def test_local_mode_with_empty_cloud_config_sends_nothing(self, dual_app, caplog):
        """云端配置全空时 local 模式不报错、不发请求、正常返回。"""
        with caplog.at_level("WARNING"):
            out = _health(
                dual_app,
                cloud_ok=False,
                local_ok=True,
                mode="local",
                cloud_base_url="",
                cloud_api_key="",
                cloud_model="",
            )
        assert out["result"]["mode"] == "local"
        assert out["result"]["status"] == "up"
        assert out["calls"] and all(
            call["base_url"] == _DualModeConfig.EMBEDDING_LOCAL_BASE_URL for call in out["calls"]
        )
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "EMBEDDING_BASE_URL" not in messages, "local 模式不读云端配置，不应报警"

    def test_local_missing_config_reports_local_model(self, dual_app, caplog):
        """本地配置缺失分支：mode=null 但 model 必须是**本地模型名**。

        与异常分支（侧车不可达）互为补充：变异成 ``_embedding_down("", …)``
        或误报云端模型名时这里必须 FAIL。
        """
        with caplog.at_level("WARNING"):
            out = _health(dual_app, cloud_ok=True, local_ok=True, local_url="", mode="local")
        assert out["result"] == {
            "mode": None,
            "model": _DualModeConfig.EMBEDDING_LOCAL_MODEL,
            "dim": 1024,
            "status": "down",
        }
        assert out["calls"] == [], "配置缺失时不应发起任何请求"
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "本地侧车配置缺失" in messages

    def test_local_missing_local_model_reports_empty_local_model(self, dual_app):
        """只缺 local_model 时同样短路，且 model 如实回显空值（不是云端名）。"""
        out = _health(dual_app, cloud_ok=True, local_ok=True, local_model="", mode="local")
        assert out["result"] == {"mode": None, "model": "", "dim": 1024, "status": "down"}
        assert out["calls"] == []

    def test_local_mode_ignores_local_enabled_flag(self, dual_app):
        """local 模式是显式选择，不受 EMBEDDING_LOCAL_ENABLED 影响。"""
        out = _health(dual_app, cloud_ok=False, local_ok=True, local_enabled=False, mode="local")
        assert out["result"]["mode"] == "local"
        assert out["result"]["status"] == "up"

    def test_local_down_endpoint_still_200_and_degraded(self, dual_client, monkeypatch):
        probes = HealthProbes(
            mysql=lambda: {"status": "up", "latency_ms": 1, "error": None},
            mongodb=lambda: {"status": "up", "latency_ms": 1, "error": None},
            redis=lambda: {"status": "up", "latency_ms": 1, "error": None},
            chroma=lambda: {"status": "up", "latency_ms": 1, "error": None},
            embedding=lambda: {
                "mode": None,
                "model": _DualModeConfig.EMBEDDING_LOCAL_MODEL,
                "dim": 1024,
                "status": "down",
            },
        )
        monkeypatch.setattr(system_service, "build_default_probes", lambda: probes)
        res = dual_client.get("/api/health")
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["status"] == "degraded"
        assert data["embedding"] == {
            "mode": None,
            "model": _DualModeConfig.EMBEDDING_LOCAL_MODEL,
            "dim": 1024,
            "status": "down",
        }


class TestCloudMode:
    """EMBEDDING_MODE=cloud：只探云端，失败不回落本地。"""

    def test_cloud_up_reports_cloud_and_skips_local(self, dual_app):
        out = _health(dual_app, cloud_ok=True, local_ok=True, mode="cloud")
        assert out["result"] == {
            "mode": "cloud",
            "model": _DualModeConfig.EMBEDDING_MODEL,
            "dim": 1024,
            "status": "up",
        }
        assert [call["base_url"] for call in out["calls"]] == [_DualModeConfig.EMBEDDING_BASE_URL]
        assert out["calls"][0]["timeout_s"] == 5.0

    def test_cloud_down_reports_null_mode_and_no_local_attempt(self, dual_app, caplog):
        with caplog.at_level("WARNING"):
            out = _health(dual_app, cloud_ok=False, local_ok=True, mode="cloud")
        assert out["result"] == {
            "mode": None,
            "model": _DualModeConfig.EMBEDDING_MODEL,
            "dim": 1024,
            "status": "down",
        }
        # cloud 模式绝不尝试本地
        assert _local_calls(out["calls"]) == []
        assert len(out["calls"]) == 1

    def test_cloud_mode_with_empty_config_sends_nothing(self, dual_app):
        out = _health(
            dual_app,
            cloud_ok=True,
            local_ok=True,
            mode="cloud",
            cloud_base_url="",
            cloud_api_key="",
            cloud_model="",
        )
        assert out["calls"] == []
        assert out["result"]["status"] == "down"
        assert out["result"]["mode"] is None


class TestAutoMode:
    """EMBEDDING_MODE=auto：旧行为——云端 → 本地 → down。"""

    def test_auto_cloud_up_prefers_cloud(self, dual_app):
        out = _health(dual_app, cloud_ok=True, local_ok=True, mode="auto")
        assert out["result"]["mode"] == "cloud"
        assert [call["base_url"] for call in out["calls"]] == [_DualModeConfig.EMBEDDING_BASE_URL]

    def test_auto_cloud_down_falls_back_to_local(self, dual_app):
        out = _health(dual_app, cloud_ok=False, local_ok=True, mode="auto")
        assert out["result"]["mode"] == "local"
        assert [call["base_url"] for call in out["calls"]] == [
            _DualModeConfig.EMBEDDING_BASE_URL,
            _DualModeConfig.EMBEDDING_LOCAL_BASE_URL,
        ]

    def test_auto_both_down_reports_cloud_model(self, dual_app):
        out = _health(dual_app, cloud_ok=False, local_ok=False, mode="auto")
        assert out["result"] == {
            "mode": None,
            "model": _DualModeConfig.EMBEDDING_MODEL,
            "dim": 1024,
            "status": "down",
        }
        assert len(out["calls"]) == 2

    def test_auto_cloud_config_incomplete_skips_cloud(self, dual_app):
        """auto 下云端配置不全仍短路（不发请求），直接走本地兜底。"""
        out = _health(
            dual_app,
            cloud_ok=True,
            local_ok=True,
            mode="auto",
            cloud_base_url="",
        )
        assert _cloud_calls(out["calls"]) == []
        assert out["result"]["mode"] == "local"


class TestShippedDefaultMode:
    """出厂默认值：未设置 EMBEDDING_MODE 时必须取 local（零云端外发）。"""

    def test_shipped_default_mode_is_local(self, monkeypatch):
        """变异（默认值 local→auto/cloud）必须在此 FAIL。"""
        from src import config as config_module

        monkeypatch.delenv("EMBEDDING_MODE", raising=False)
        assert config_module._env_choice("EMBEDDING_MODE", "local", ("local", "cloud", "auto")) == (
            "local"
        )

    def test_config_class_default_is_local(self, monkeypatch):
        """Config.EMBEDDING_MODE 的出厂值同样是 local（类属性级断言）。"""
        from src.config import Config

        assert Config.EMBEDDING_MODE == "local"

    def test_service_layer_default_mode_is_local(self):
        """service 层缺省值也是 local：漏传 mode 时绝不外发云端。"""
        import inspect

        default = inspect.signature(_embedding_health).parameters["mode"].default
        assert default == "local"

    def test_default_probes_local_without_cloud_request(self, monkeypatch):
        """端到端默认路径：不设 EMBEDDING_MODE 时配置解析 → 探针只打本地。"""
        from src.app import create_app
        from src.config import Config

        monkeypatch.delenv("EMBEDDING_MODE", raising=False)
        # 仅替换「读的是哪个环境变量」，保证拿到的是未设置时的默认值
        app = create_app(type("_Default", (Config,), {"TESTING": True}))
        stub = _StubPing()
        monkeypatch.setattr(system_service, "_embedding_ping", stub)
        with app.app_context():
            result = system_service.build_default_probes().embedding()
        assert result == {
            "mode": "local",
            "model": Config.EMBEDDING_LOCAL_MODEL,
            "dim": Config.EMBEDDING_DIM,
            "status": "up",
        }
        assert [call["base_url"] for call in stub.calls] == [Config.EMBEDDING_LOCAL_BASE_URL]


class TestModeValidation:
    """EMBEDDING_MODE 非法取值 → 回退 local 并落 WARNING。"""

    @pytest.mark.parametrize("bad_mode", ["LOCALX", "", "  ", "Cloudy", "localx # 笔误"])
    def test_invalid_mode_falls_back_to_local(self, dual_app, caplog, bad_mode):
        with caplog.at_level("WARNING"):
            out = _health(dual_app, cloud_ok=True, local_ok=True, mode=bad_mode)
        assert out["result"]["mode"] == "local"
        assert _cloud_calls(out["calls"]) == [], "非法取值必须按 local 处理，不得外发云端"
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "EMBEDDING_MODE 取值非法" in messages

    @pytest.mark.parametrize(("raw_mode", "expected"), [("Local", "local"), (" LOCAL ", "local")])
    def test_mode_value_is_case_and_space_insensitive(self, dual_app, raw_mode, expected):
        """大小写 / 首尾空白同样归一化，不因写法差异误判为非法。"""
        out = _health(dual_app, cloud_ok=True, local_ok=True, mode=raw_mode)
        assert out["result"]["mode"] == expected
        assert _cloud_calls(out["calls"]) == []

    # 行内注释用例必须是**非默认值**：若取 "local # 默认"，剥注释逻辑被删掉时
    # 会因非法而回退默认值 local，断言恒真（空断言）。用 cloud/auto 才能钉住。
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("local", "local"),
            ("cloud", "cloud"),
            ("auto", "auto"),
            ("cloud # 切云端", "cloud"),
            ("auto # 云端优先+本地兜底", "auto"),
            ("CLOUD", "cloud"),
        ],
    )
    def test_env_choice_accepts_valid_values(self, monkeypatch, raw, expected):
        from src import config as config_module

        monkeypatch.setenv("__B0BE3_MODE__", raw)
        assert (
            config_module._env_choice("__B0BE3_MODE__", "local", ("local", "cloud", "auto"))
            == expected
        )

    @pytest.mark.parametrize("raw", ["LOCALX", "", "   ", "cloudy # 笔误"])
    def test_env_choice_falls_back_and_warns(self, monkeypatch, caplog, raw):
        from src import config as config_module

        monkeypatch.setenv("__B0BE3_MODE__", raw)
        with caplog.at_level("WARNING"):
            value = config_module._env_choice(
                "__B0BE3_MODE__", "local", ("local", "cloud", "auto")
            )
        assert value == "local"
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "__B0BE3_MODE__" in messages and "回退默认值" in messages

    def test_env_choice_unset_is_silent_default(self, monkeypatch, caplog):
        from src import config as config_module

        monkeypatch.delenv("__B0BE3_MODE__", raising=False)
        with caplog.at_level("WARNING"):
            assert (
                config_module._env_choice("__B0BE3_MODE__", "local", ("local", "cloud", "auto"))
                == "local"
            )
        assert caplog.records == []

    def test_default_probe_passes_mode_from_config(self, dual_app, monkeypatch):
        """配置 → 探针接线：build_default_probes 必须把 EMBEDDING_MODE 传下去。"""
        stub = _StubPing()
        monkeypatch.setattr(system_service, "_embedding_ping", stub)
        with dual_app.app_context():
            result = system_service.build_default_probes().embedding()
        # _DualModeConfig.EMBEDDING_MODE = "auto"
        assert result["mode"] == "cloud"
        assert [call["base_url"] for call in stub.calls] == [_DualModeConfig.EMBEDDING_BASE_URL]


class TestLocalSidecarDirectConnection:
    """本地侧车必须直连：系统代理（Clash 等）不得劫持 127.0.0.1 探活。"""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            # ---- 回环（必须直连）----
            ("http://127.0.0.1:8010/v1", True),
            ("http://127.0.0.2:8010/v1", True),  # 127/8 其他地址
            ("http://127.1:8010/v1", True),  # inet_aton 简写
            ("http://localhost:8010/v1", True),
            ("http://LOCALHOST:8010/v1", True),  # 大小写
            ("http://localhost.:8010/v1", True),  # 尾点
            ("http://[::1]:8010/v1", True),
            ("http://[::ffff:127.0.0.1]:8010/v1", True),  # IPv4-mapped
            ("http://0.0.0.0:8010/v1", True),  # 有意列入：本机监听等价
            # ---- 非回环（保持系统代理）----
            ("https://maas.example.com/v1", False),
            ("http://172.20.10.5:8010/v1", False),  # docker / 局域网地址
            ("http://host.docker.internal:8010/v1", False),  # macOS 容器宿主别名
            ("http://127.0.0.1.nip.io:8010/v1", False),  # 解析到回环但不是字面回环
            ("", False),
            ("not-a-url", False),
        ],
    )
    def test_is_loopback(self, url, expected):
        assert system_service._is_loopback(url) is expected

    def test_local_ping_uses_proxy_bypassing_client(self, monkeypatch):
        """回环地址构建的客户端必须 trust_env=False（零系统代理依赖）。"""
        captured = {}

        class _FakeClient:
            def __init__(self, **kwargs):
                captured["client_kwargs"] = kwargs

            def close(self):
                captured["closed"] = True

        import openai

        class _FakeOpenAI:
            def __init__(self, **kwargs):
                captured["openai_kwargs"] = kwargs

            class embeddings:
                @staticmethod
                def create(**_kwargs):
                    return object()

        monkeypatch.setattr(openai, "DefaultHttpxClient", _FakeClient)
        monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
        system_service._embedding_ping("http://127.0.0.1:8010/v1", "local", "m", 15.0)
        assert captured["client_kwargs"]["trust_env"] is False
        assert captured["openai_kwargs"]["http_client"] is not None
        assert captured["closed"] is True

    def test_proxy_bypass_client_works_with_real_sdk(self):
        """真实 SDK 联调：DefaultHttpxClient(trust_env=False) 可被 OpenAI 接受。"""
        import openai

        client = openai.DefaultHttpxClient(trust_env=False, timeout=1.0)
        try:
            sdk = openai.OpenAI(
                base_url="http://127.0.0.1:9/v1", api_key="x", timeout=1.0, http_client=client
            )
            assert sdk is not None
        finally:
            client.close()

    def test_cloud_ping_keeps_env_trust(self, monkeypatch):
        """云端地址不受影响：仍使用默认客户端（可走系统代理出海）。"""
        captured = {}

        import openai

        class _FakeOpenAI:
            def __init__(self, **kwargs):
                captured["openai_kwargs"] = kwargs

            class embeddings:
                @staticmethod
                def create(**_kwargs):
                    return object()

        monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
        system_service._embedding_ping("https://cloud.invalid/v1", "k", "m", 5.0)
        assert captured["openai_kwargs"]["http_client"] is None
        assert captured["openai_kwargs"]["max_retries"] == 0

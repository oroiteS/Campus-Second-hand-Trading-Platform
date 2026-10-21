"""system 路由冒烟：health / openapi.json / docs 与全局错误 envelope 兜底。"""

import re

from src.services import system_service
from src.services.system_service import HealthProbes

CHECKED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$")


def _up_probe(latency_ms: int = 2):
    return lambda: {"status": "up", "latency_ms": latency_ms, "error": None}


def _down_probe():
    return lambda: {"status": "down", "latency_ms": None, "error": "ConnectionRefusedError: 拒绝"}


def _cloud_up():
    return {"mode": "cloud", "model": "test-model", "dim": 1024, "status": "up"}


def _cloud_down():
    return {"mode": None, "model": "test-model", "dim": 1024, "status": "down"}


def _probes(**overrides) -> HealthProbes:
    fields = {
        "mysql": _up_probe(),
        "mongodb": _up_probe(),
        "redis": _up_probe(),
        "chroma": _up_probe(),
        "embedding": _cloud_up,
    }
    fields.update(overrides)
    return HealthProbes(**fields)


class TestHealthService:
    """service 层聚合逻辑（探针注入，不触真实依赖）。"""

    def test_all_up_aggregates_ok(self, app):
        with app.app_context():
            data = system_service.check_health(_probes())
        assert data["status"] == "ok"
        assert CHECKED_AT_RE.match(data["checked_at"])
        assert set(data["services"]) == {"mysql", "mongodb", "redis", "chroma"}
        assert data["embedding"] == _cloud_up()

    def test_one_service_down_aggregates_degraded(self, app):
        with app.app_context():
            data = system_service.check_health(_probes(mysql=_down_probe()))
        assert data["status"] == "degraded"
        assert data["services"]["mysql"]["status"] == "down"
        assert data["services"]["mysql"]["latency_ms"] is None
        assert data["services"]["redis"]["status"] == "up"

    def test_embedding_down_alone_degrades(self, app):
        with app.app_context():
            data = system_service.check_health(_probes(embedding=_cloud_down))
        assert data["status"] == "degraded"
        assert data["embedding"]["mode"] is None


class TestHealthEndpoint:
    def test_all_up_envelope_and_structure(self, client, monkeypatch):
        monkeypatch.setattr(system_service, "build_default_probes", lambda: _probes())
        res = client.get("/api/health")
        assert res.status_code == 200
        body = res.get_json()
        assert set(body) == {"code", "message", "data"}
        assert body["code"] == 0
        assert body["message"] == "ok"
        data = body["data"]
        assert set(data) == {"status", "checked_at", "services", "embedding"}
        assert data["status"] == "ok"
        assert CHECKED_AT_RE.match(data["checked_at"])
        for name in ("mysql", "mongodb", "redis", "chroma"):
            assert set(data["services"][name]) == {"status", "latency_ms", "error"}
            assert data["services"][name]["status"] == "up"
            assert isinstance(data["services"][name]["latency_ms"], int)
            assert data["services"][name]["error"] is None
        assert set(data["embedding"]) == {"mode", "model", "dim", "status"}
        assert data["embedding"]["mode"] == "cloud"

    def test_degraded_still_http_200(self, client, monkeypatch):
        probes = _probes(redis=_down_probe(), embedding=_cloud_down)
        monkeypatch.setattr(system_service, "build_default_probes", lambda: probes)
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.get_json()["code"] == 0
        data = res.get_json()["data"]
        assert data["status"] == "degraded"
        assert data["services"]["redis"] == {
            "status": "down",
            "latency_ms": None,
            "error": "ConnectionRefusedError: 拒绝",
        }
        assert data["embedding"]["mode"] is None
        assert data["embedding"]["status"] == "down"


class TestOpenApiEndpoints:
    def test_openapi_json_is_raw_spec(self, client):
        res = client.get("/api/openapi.json")
        assert res.status_code == 200
        doc = res.get_json()
        assert doc["openapi"] == "3.0.3"
        # 契约已冻结为 0.2.0（b1 用户域 12 接口并入）
        assert doc["info"]["version"] == "0.2.0"
        assert set(doc["paths"]) == {
            "/health",
            "/openapi.json",
            "/docs",
            "/auth/register",
            "/auth/login",
            "/auth/logout",
            "/auth/password/reset",
            "/users/me",
            "/users/me/password",
            "/users/me/avatar",
            "/certification/applications",
            "/certification/applications/mine",
            "/schools",
            "/images/{id}",
        }
        assert res.content_type.startswith("application/json")

    def test_docs_page_serves_html(self, client):
        res = client.get("/api/docs")
        assert res.status_code == 200
        assert res.content_type.startswith("text/html")


class TestErrorEnvelope:
    def test_unknown_path_404_envelope(self, client):
        res = client.get("/api/no-such-path")
        assert res.status_code == 404
        body = res.get_json()
        assert set(body) == {"code", "message", "data"}
        assert body["code"] == 9002
        assert body["data"] is None

    def test_method_not_allowed_envelope(self, client):
        res = client.delete("/api/health")
        assert res.status_code == 405
        body = res.get_json()
        assert set(body) == {"code", "message", "data"}
        assert body["code"] == 9002

    def test_unhandled_exception_500_envelope(self, app, client):
        @app.get("/api/__boom")
        def _boom():
            raise RuntimeError("boom")

        res = client.get("/api/__boom")
        assert res.status_code == 500
        body = res.get_json()
        assert set(body) == {"code", "message", "data"}
        assert body["code"] == 9005
        assert body["data"] is None
        assert "boom" not in body["message"]  # 内部错误细节不外泄

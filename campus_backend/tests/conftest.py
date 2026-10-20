"""pytest 公共 fixture：应用与测试客户端。"""

import pytest

from src.app import create_app
from src.config import Config


class TestConfig(Config):
    """测试配置：不依赖真实凭据（依赖探针在各用例内注入替换）。"""

    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    return create_app(TestConfig)


@pytest.fixture()
def client(app):
    return app.test_client()

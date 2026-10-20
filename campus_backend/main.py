"""应用入口：仅 import + main()（main 内只有 app.run）。

模块级 ``app = create_app()`` 供 WSGI 服务器与 Flask CLI
（``flask --app main ...``，迁移命令即经此入口）引用。
"""

from src.app import create_app

app = create_app()


def main() -> None:
    app.run(host=app.config["HOST"], port=app.config["PORT"])


if __name__ == "__main__":
    main()

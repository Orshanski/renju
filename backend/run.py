"""Uvicorn entry point. По образцу librarium-py/backend/run.py.

  uv run python run.py            # HTTP  на :8000 (локально)
  uv run python run.py --ssl      # HTTPS на :8000 (сертификаты Tailscale из ~/dev-ca)
  uv run python run.py --ssl --dev  # + авто-reload по app/

TLS терминируем сами (как librarium), а не через `tailscale serve`: Safari/клиент
ходит к uvicorn по настоящему HTTPS. Бэкенд отдаёт собранный фронт (frontend/dist).
"""

import os
import sys

import uvicorn


def run_server(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    dev = "--dev" in args
    ssl = "--ssl" in args

    kwargs: dict = dict(
        host="0.0.0.0",
        port=8000,
        factory=True,  # app.app_factory:create_app — фабрика (Settings по умолчанию)
        reload=dev,
        reload_dirs=["app"] if dev else None,
    )

    if ssl:
        cert_dir = os.path.expanduser("~/dev-ca")
        kwargs["ssl_keyfile"] = os.path.join(cert_dir, "tailscale.key")
        kwargs["ssl_certfile"] = os.path.join(cert_dir, "tailscale.crt")

    uvicorn.run("app.app_factory:create_app", **kwargs)


if __name__ == "__main__":
    run_server()

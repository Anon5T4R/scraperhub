"""Ponto de entrada do executavel: sobe o servidor e abre o navegador."""
from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn

from app.main import app as fastapi_app

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"


def main() -> None:
    server = uvicorn.Server(uvicorn.Config(fastapi_app, host=HOST, port=PORT, log_level="warning"))

    def _open_browser() -> None:
        # espera o servidor aceitar conexoes antes de abrir a aba
        for _ in range(60):
            if server.started:
                break
            time.sleep(0.5)
        webbrowser.open(URL)

    threading.Thread(target=_open_browser, daemon=True).start()
    print(f"ScraperHub rodando em {URL} (Ctrl+C para sair)")
    server.run()


if __name__ == "__main__":
    main()

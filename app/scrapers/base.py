"""Classe base, tipos e erros comuns aos scrapers do ScraperHub."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Literal

Kind = Literal["manga", "video", "image", "ebook", "file", "site"]
ProgressCb = Callable[[int, str], None]


def app_root() -> Path:
    """Raiz do app: pasta do exe (PyInstaller) ou do projeto (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = app_root()
DOWNLOADS_DIR = PROJECT_ROOT / "downloads"


class ScraperError(Exception):
    """Erro tipado levantado por um scraper, com mensagem amigavel."""


class Scraper:
    """Contrato comum a todos os scrapers."""

    id: str = "base"
    label: str = "Base"
    kind: Kind = "video"

    def match(self, url: str) -> bool:
        """Retorna True se este scraper aceita a URL informada."""
        raise NotImplementedError

    def get_info(self, url: str) -> dict:
        """Retorna metadados (title, cover) e a lista de itens disponiveis."""
        raise NotImplementedError

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        """Baixa os itens indicados, reportando progresso via callback."""
        raise NotImplementedError

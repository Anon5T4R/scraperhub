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
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# UA do Chromium efetivamente em uso, preenchido quando o navegador sobe (ver
# `browser.run`). Ate la, os clients httpx do processo usam o fallback acima.
_synced_user_agent: str | None = None


def chromium_user_agent(chromium_version: str) -> str:
    """Compõe o User-Agent a partir da versão do Chromium em uso.

    Só o major importa para os sites, então o token do Chrome vira
    "<major>.0.0.0" — evita expor a versão completa (ex "130.0.6723.44") e
    mantém o UA coerente com o navegador que de fato faz as requisições.
    """
    major = str(chromium_version).split(".")[0] or "124"
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    )


def set_current_user_agent(user_agent: str) -> None:
    """Registra (cache por processo) o UA do navegador em uso."""
    global _synced_user_agent
    _synced_user_agent = user_agent


def current_user_agent() -> str:
    """UA sincronizado com o Chromium, se já conhecido; senão o fallback."""
    return _synced_user_agent or USER_AGENT


class ScraperError(Exception):
    """Erro tipado levantado por um scraper, com mensagem amigavel.

    `challenge=True` sinaliza que o site exigiu verificacao humana: a UI pode
    oferecer o modo assistido (abrir uma janela para o usuario resolver) em
    vez de so mostrar o erro.
    """

    challenge: bool = False


class TaskCancelled(Exception):
    """Levantado quando o usuario cancela uma tarefa em andamento."""


class Scraper:
    """Contrato comum a todos os scrapers."""

    id: str = "base"
    label: str = "Base"
    kind: Kind = "video"
    supports_challenge: bool = False

    def match(self, url: str) -> bool:
        """Retorna True se este scraper aceita a URL informada."""
        raise NotImplementedError

    def solve_challenge(self, url: str, progress_cb: ProgressCb) -> None:
        """Abre uma janela para o usuario resolver a verificacao humana.

        Scrapers que nao exigem intervencao humana (o padrao) recusam.
        """
        raise ScraperError("Este scraper nao requer verificacao humana.")

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

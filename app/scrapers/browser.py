"""Utilitarios Playwright para scrapers de sites renderizados por JS."""
from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright

from .base import ScraperError, app_root

DEFAULT_TIMEOUT_MS = 30000
VIEWPORT = {"width": 1366, "height": 900}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _driver_cli() -> list[str] | None:
    """Comando do CLI do driver Playwright empacotado (node + cli.js)."""
    base = Path(getattr(sys, "_MEIPASS", "")) / "playwright" / "driver"
    node = base / "node.exe"
    cli = base / "package" / "cli.js"
    if node.is_file() and cli.is_file():
        return [str(node), str(cli)]
    return None


def _bundled_browsers() -> Path | None:
    """Pasta ms-playwright embutida no exe (PyInstaller), se houver."""
    base = Path(getattr(sys, "_MEIPASS", "")) / "ms-playwright"
    if base.is_dir() and any(base.glob("chromium*")):
        return base
    return None


def _ensure_chromium(pw) -> None:
    """Garante que o Chromium existe; instala via driver CLI se faltar."""
    try:
        exe = Path(pw.chromium.executable_path)
        if exe.is_file():
            return
    except Exception:
        pass
    # shell headless embutido nao aparece em executable_path mas serve
    if _bundled_browsers() is not None:
        return
    cmd = _driver_cli()
    if not cmd:
        raise ScraperError(
            "Chromium do Playwright nao encontrado. Rode "
            "'python -m playwright install chromium' e tente novamente."
        )
    try:
        subprocess.run(cmd + ["install", "chromium"], check=True, timeout=600)
    except Exception as exc:
        raise ScraperError(f"Falha ao instalar o Chromium automaticamente: {exc}") from exc


@contextmanager
def run(headless: bool = True) -> Iterator[BrowserContext]:
    """Soba um Chromium e entrega um contexto; fecha tudo ao sair.

    No executavel (PyInstaller): usa os browsers EMBUTIDOS no exe
    (ms-playwright empacotado); se ausentes, instala em pasta persistente ao
    lado do exe na primeira execucao.
    """
    if getattr(sys, "frozen", False):
        bundled = _bundled_browsers()
        if bundled is not None:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
        else:
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(app_root() / "pw-browsers"))
    with sync_playwright() as pw:
        _ensure_chromium(pw)
        try:
            browser = pw.chromium.launch(headless=headless)
        except Exception as exc:
            raise ScraperError(f"Nao foi possivel iniciar o Chromium: {exc}") from exc
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="pt-BR",
            viewport=VIEWPORT,
        )
        try:
            yield context
        finally:
            context.close()
            browser.close()


def scroll_until_stable(
    page: Page,
    selector: str,
    max_iter: int = 50,
    wait_ms: int = 1000,
    container: str | None = None,
) -> int:
    """Rola ate a contagem de `selector` parar de crescer; retorna a contagem.

    Com `container`, rola o scroll interno desse seletor (ex: lista de
    capitulos). Sem `container`, usa o scroll da pagina via roda do mouse
    (ex: imagens do leitor com lazy-load).
    """
    previous = -1
    count = 0
    for _ in range(max_iter):
        count = page.eval_on_selector_all(selector, "els => els.length")
        if count == previous and count > 0:
            break
        previous = count
        if container:
            page.eval_on_selector_all(
                container,
                "els => els.forEach(el => { el.scrollTop = el.scrollHeight; })",
            )
        else:
            page.mouse.wheel(0, 4000)
        page.wait_for_timeout(wait_ms)
    return count


def download_binary(page: Page, url: str) -> bytes:
    """Baixa os bytes de uma URL herdando cookies/TLS do navegador.

    Envia o Referer da pagina atual: alguns CDNs de manga rejeitam (403)
    requisicoes sem referer.
    """
    response = page.context.request.get(url, headers={"Referer": page.url})
    if not response.ok:
        raise ScraperError(f"Falha ao baixar arquivo ({response.status}): {url}")
    return response.body()

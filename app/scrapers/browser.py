"""Utilitarios Playwright para scrapers de sites renderizados por JS."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright

from .base import ScraperError

DEFAULT_TIMEOUT_MS = 30000
VIEWPORT = {"width": 1366, "height": 900}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@contextmanager
def run(headless: bool = True) -> Iterator[BrowserContext]:
    """Sobe um Chromium e entrega um contexto; fecha tudo ao sair."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
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

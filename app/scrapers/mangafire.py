"""Scraper de manga para sites SPA no estilo mangafire.to (Playwright)."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Page

from . import browser
from .base import DOWNLOADS_DIR, ProgressCb, Scraper, ScraperError
from .mangafire_parse import (
    TITLE_PATH_RE,
    chapter_folder,
    chapter_label,
    image_extension,
    make_cbz,
    order_items,
    parse_chapter_id,
    parse_title_url,
    sanitize,
    select_ascending,
)

TITLE_ROW_SELECTOR = "a.title-detail__row-link"
CHAPTER_IMG_SELECTOR = "img.reader-img"
INFO_TIMEOUT_MS = 30000
NAV_TIMEOUT_MS = 45000
LIST_WAIT_MS = 1200
IMG_MAX_ITER = 60
IMG_WAIT_MS = 700
IMG_FIRST_TIMEOUT_MS = 10000
DELAY_S = 0.3
CHAPTER_GAP_S = 2.0
CHAPTER_COOLDOWN_S = 60
COOLDOWN_STEP_S = 5
IMG_ATTEMPTS = 2
MAX_CONSECUTIVE_FAILURES = 5
CHALLENGE_HINTS = (
    "challenge-form",
    "cf-challenge",
    "just a moment",
    "attention required",
    # Turnstile interativo (Security check) — visto em bloqueio por taxa
    "verify you're human",
    "security check",
    "cf-turnstile",
    "click the shapes",
)


class SiteBlocked(ScraperError):
    """O site pediu verificacao humana (CAPTCHA): abortar sem retry."""


# Um download mangafire por vez: duas tarefas simultaneas no mesmo site
# disparam o bloqueio anti-bot (Turnstile) rapidamente.
_DOWNLOAD_LOCK = threading.Lock()


def is_challenge_html(low_html: str) -> bool:
    """True se o HTML parece uma pagina de bloqueio/challenge."""
    return any(hint in low_html for hint in CHALLENGE_HINTS)


def cooldown(progress_cb: ProgressCb, progress: int, seconds: int) -> None:
    """Pausa longa apos falha, em passos curtos: o progresso continua
    reportando (e o cancelamento da tarefa e percebido na hora)."""
    remaining = seconds
    while remaining > 0:
        step = min(COOLDOWN_STEP_S, remaining)
        progress_cb(progress, f"Capitulo falhou — esfriando o site: {remaining}s ate o proximo...")
        time.sleep(step)
        remaining -= step

ROWS_JS = """
els => els.map(e => ({
    href: e.getAttribute('href') || '',
    num: (e.querySelector('.title-detail__row-num')?.innerText || '').trim(),
    sub: (e.querySelector('.title-detail__row-sub')?.innerText || '').trim(),
    flag: (
        e.closest('.title-detail__row')?.querySelector('.title-detail__row-flag')?.getAttribute('title')
        || ''
    ).trim()
}))
"""

IMAGES_JS = "els => els.map(e => e.currentSrc || e.src || '').filter(u => u.startsWith('http'))"


class MangaFireScraper(Scraper):
    """Scraper para mangafire.to e clones com o mesmo front renderizado por JS."""

    id = "mangafire"
    label = "MangaFire"
    kind = "manga"

    def match(self, url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if "mangafire" in host:
            return True
        path = parsed.path or ""
        return bool(TITLE_PATH_RE.match(path)) or "/chapter/" in path

    def get_info(self, url: str) -> dict:
        with browser.run() as context:
            page = self._new_page(context)
            try:
                return self._read_info(page, url)
            finally:
                page.close()

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        options = options or {}
        title_url = parse_title_url(url)
        if _DOWNLOAD_LOCK.locked():
            progress_cb(0, "Aguardando outro download MangaFire terminar (evita bloqueio)...")
        with _DOWNLOAD_LOCK:
            self._download_all(title_url, item_ids, progress_cb, options)

    def _download_all(
        self,
        title_url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict,
    ) -> None:
        with browser.run() as context:
            page = self._new_page(context)
            try:
                info = self._read_info(page, title_url)
            finally:
                page.close()
            title = sanitize(str(info["title"]))
            ordered = select_ascending(info["items"], item_ids)
            if not ordered:
                raise ScraperError("Nenhum capitulo valido foi selecionado.")
            total = len(ordered)
            falhas: list[str] = []
            consecutivas = 0
            for index, item in enumerate(ordered, start=1):
                label = str(item["label"])
                progress_cb(
                    int((index - 1) / total * 100),
                    f"Iniciando capitulo {label} ({index}/{total})",
                )
                chapter_page = self._new_page(context)
                try:
                    falha = self._download_chapter(
                        chapter_page,
                        title_url,
                        DOWNLOADS_DIR / title,
                        index,
                        item,
                        progress_cb,
                        options,
                        total,
                    )
                finally:
                    chapter_page.close()
                if falha:
                    falhas.append(falha)
                    consecutivas += 1
                    if consecutivas >= MAX_CONSECUTIVE_FAILURES:
                        restantes = total - index
                        resumo = "; ".join(falhas[-MAX_CONSECUTIVE_FAILURES:])
                        raise ScraperError(
                            f"{MAX_CONSECUTIVE_FAILURES} capitulos seguidos sem paginas "
                            f"({resumo}). Abortados {restantes} restante(s) para nao "
                            "piorar um provavel bloqueio do site — espere alguns "
                            "minutos e tente de novo (os ja baixados sao pulados)."
                        )
                    # pausa adaptativa: sitio irritado -> esfriar antes do proximo
                    cooldown(
                        progress_cb,
                        int(index / total * 100),
                        CHAPTER_COOLDOWN_S,
                    )
                    continue
                consecutivas = 0
                progress_cb(
                    int(index / total * 100),
                    f"Concluido capitulo {label} ({index}/{total})",
                )
                if index < total:
                    time.sleep(CHAPTER_GAP_S)
            if falhas:
                resumo = "; ".join(falhas[:10]) + (" ..." if len(falhas) > 10 else "")
                raise ScraperError(
                    f"{len(falhas)}/{total} capitulo(s) sem paginas ( falha: {resumo} )"
                )

    @staticmethod
    def _new_page(context: BrowserContext) -> Page:
        page = context.new_page()
        page.set_default_timeout(INFO_TIMEOUT_MS)
        return page

    def _read_info(self, page: Page, url: str) -> dict:
        title_url = parse_title_url(url)
        try:
            page.goto(title_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            page.wait_for_selector("h1", timeout=INFO_TIMEOUT_MS)
            page.wait_for_selector(TITLE_ROW_SELECTOR, timeout=INFO_TIMEOUT_MS)
            title = (page.inner_text("h1") or "").strip()
            cover_el = page.query_selector('meta[property="og:image"]') or page.query_selector("img.poster, .poster img")
            cover = cover_el.get_attribute("content") if cover_el and cover_el.get_attribute("content") else None
            rows = self._all_chapter_rows(page)
        except Exception as exc:
            raise ScraperError(f"Falha ao ler a pagina do manga: {exc}") from exc
        items = self._items(rows)
        if not items:
            raise ScraperError("Nenhum capitulo encontrado nesta pagina.")
        return {"title": title or "Manga sem titulo", "cover": cover, "items": items}

    def _all_chapter_rows(self, page: Page) -> list[dict]:
        """Coleta os capitulos de TODAS as paginas do npager (20 por pagina).

        A lista usa botoes de paginacao (npager__num), entao o scroll nao
        carrega mais nada: e preciso clicar na proxima pagina. Com ellipsis
        ('1 2 3 4 5 ... N'), clica o maior numero disponivel maior que o
        ativo — o npager re-renderiza e o loop continua.
        """
        all_rows: list[dict] = []
        seen: set[str] = set()
        while True:
            page.wait_for_timeout(LIST_WAIT_MS)
            for row in page.eval_on_selector_all(TITLE_ROW_SELECTOR, ROWS_JS):
                chapter_id = parse_chapter_id(str(row.get("href") or ""))
                if chapter_id and chapter_id not in seen:
                    seen.add(chapter_id)
                    all_rows.append(row)
            clicked = page.evaluate(
                """() => {
                    const btns = Array.from(document.querySelectorAll('.npager__num'));
                    const active = btns.find(b => b.classList.contains('is-active'));
                    const current = active ? parseInt(active.innerText, 10) : 0;
                    let target = null;
                    let targetNum = current;
                    for (const b of btns) {
                        const n = parseInt(b.innerText.trim(), 10);
                        if (!isNaN(n) && n > targetNum) { target = b; targetNum = n; }
                    }
                    if (target) { target.click(); return true; }
                    return false;
                }"""
            )
            if not clicked:
                break
        return all_rows

    @staticmethod
    def _items(rows: list[dict]) -> list[dict]:
        items: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            chapter_id = parse_chapter_id(str(row.get("href") or ""))
            if not chapter_id or chapter_id in seen:
                continue
            seen.add(chapter_id)
            label = chapter_label(str(row.get("num") or ""), str(row.get("sub") or ""))
            flag = str(row.get("flag") or "")
            if flag:
                # o mesmo numero existe em varios idiomas: sem isso o
                # usuario baixa 3x "Ch. 49" sem saber a diferenca
                label = f"{label} [{flag}]"
            items.append(
                {
                    "id": chapter_id,
                    "label": label,
                    "flag": flag,
                }
            )
        return order_items(items)

    def _download_chapter(
        self,
        page: Page,
        title_url: str,
        base: Path,
        index: int,
        item: dict,
        progress_cb: ProgressCb,
        options: dict,
        total: int,
    ) -> str | None:
        """Baixa um capitulo; retorna motivo de falha ou None se ok."""
        label = str(item["label"])
        folder = base / chapter_folder(index, label)
        chapter_url = f"{title_url}/chapter/{item['id']}"
        images: list[str] = []
        last_error: Exception | None = None
        for attempt in range(1, IMG_ATTEMPTS + 1):
            try:
                images = self._load_chapter_images(page, chapter_url)
            except SiteBlocked:
                raise  # CAPTCHA: retry so piora o bloqueio
            except Exception as exc:  # navegacao/timeout: uma retentativa
                last_error = exc
                images = []
            if images:
                break
            if attempt < IMG_ATTEMPTS:
                progress_cb(
                    int((index - 1) / total * 100),
                    f"Sem paginas em {label} (tentativa {attempt}); recarregando...",
                )
        if not images:
            motivo = f"{label}: {last_error}" if last_error else f"{label}: reader sem imagens"
            progress_cb(int((index - 1) / total * 100), f"Falhou {motivo}")
            return motivo
        if folder.exists() and self._page_count(folder) == len(images):
            progress_cb(int((index - 1) / total * 100), f"Capitulo {label} ja baixado, pulando")
            return None
        folder.mkdir(parents=True, exist_ok=True)
        for position, image_url in enumerate(images, start=1):
            data = browser.download_binary(page, image_url)
            extension = image_extension(image_url, data)
            (folder / f"{position:03d}{extension}").write_bytes(data)
            percent = int(((index - 1) + position / len(images)) / total * 100)
            progress_cb(percent, f"Cap {label}/pg {position}")
            time.sleep(DELAY_S)
        if options.get("cbz"):
            make_cbz(folder)
        return None

    def _load_chapter_images(self, page: Page, chapter_url: str) -> list[str]:
        """Abre a pagina do capitulo e coleta as imagens do reader.

        Levanta SiteBlocked imediatamente se a pagina for um challenge do
        Cloudflare/Turnstile (martelar os proximos capitulos so piora o
        bloqueio e o CAPTCHA nao e burlado).
        """
        page.goto(chapter_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        try:
            page.wait_for_selector(CHAPTER_IMG_SELECTOR, timeout=IMG_FIRST_TIMEOUT_MS)
        except Exception:
            if is_challenge_html(page.content().lower()):
                raise SiteBlocked(
                    "Site pediu verificacao humana (CAPTCHA). Cancele, espere "
                    "alguns minutos e tente de novo — o ScraperHub nao burla "
                    "CAPTCHA. Os capitulos ja baixados sao pulados no retry."
                )
            # sem imagens em IMG_FIRST_TIMEOUT_MS: segue para o scroll,
            # que cobre readers lentos/lazy
        browser.scroll_until_stable(page, CHAPTER_IMG_SELECTOR, IMG_MAX_ITER, IMG_WAIT_MS)
        images = self._chapter_images(page)
        if not images and is_challenge_html(page.content().lower()):
            raise SiteBlocked(
                "Site pediu verificacao humana (CAPTCHA). Cancele, espere "
                "alguns minutos e tente de novo."
            )
        return images

    @staticmethod
    def _chapter_images(page: Page) -> list[str]:
        urls = page.eval_on_selector_all(CHAPTER_IMG_SELECTOR, IMAGES_JS)
        result: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                result.append(url)
        return result

    @staticmethod
    def _page_count(folder: Path) -> int:
        return sum(1 for entry in folder.iterdir() if entry.is_file())

"""Scraper de manga para sites SPA no estilo mangafire.to (Playwright)."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Page

from . import browser
from .base import DOWNLOADS_DIR, ProgressCb, Scraper, ScraperError, app_root
from .mangafire_parse import (
    TITLE_PATH_RE,
    chapter_label,
    chapter_number,
    image_extension,
    make_cbz,
    numbered_folder,
    order_items,
    parse_chapter_id,
    parse_title_url,
    parse_volume_id,
    sanitize,
    select_ascending,
)
from .mangafire_state import (
    folder_pages,
    is_complete,
    load_state,
    migrate_entries,
    record_done,
    save_state,
)

TITLE_ROW_SELECTOR = "a.title-detail__row-link"
TAB_SELECTOR = "button.title-detail__tab"
CHAPTER_IMG_SELECTOR = "img.reader-img"
INFO_TIMEOUT_MS = 30000
NAV_TIMEOUT_MS = 45000
LIST_WAIT_MS = 1200
IMG_MAX_ITER = 60
# o reader de volume lazy-carrega MUITO mais paginas que o de capitulo
# Varredura do swiper de volume: espera por passo de slide e passos sem
# pagina nova antes de declarar o fim da coleta.
IMG_STEP_WAIT_MS = 250
VOLUME_STALE_STEPS = 4
IMG_WAIT_MS = 700
IMG_FIRST_TIMEOUT_MS = 10000
DELAY_S = 0.3
CHAPTER_GAP_S = 2.0
CHAPTER_COOLDOWN_S = 60
COOLDOWN_STEP_S = 5
IMG_ATTEMPTS = 2
MAX_CONSECUTIVE_FAILURES = 5
# Itens de volume chegam da UI com este prefixo no id ("vol:{id}"); o resto
# da lista e capitulo.
VOLUME_PREFIX = "vol:"
# Modo assistido: tempo maximo esperando o usuario resolver o challenge, e
# intervalo de verificacao (tambem serve de batida do cancelamento).
CHALLENGE_WAIT_S = 300
CHALLENGE_POLL_MS = 1500
# Cookies (cf_clearance) salvos aqui e reaproveitados nos proximos contextos.
STATE_PATH = app_root() / "mangafire-state.json"
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

    challenge = True


CAPTCHA_MESSAGE = (
    "Site pediu verificacao humana (CAPTCHA). Use 'Resolver verificacao' "
    "para abrir a janela e resolver, ou espere alguns minutos e tente de "
    "novo — o ScraperHub nao burla CAPTCHA. Os capitulos ja baixados sao "
    "pulados no retry."
)

# Um download mangafire por vez: duas tarefas simultaneas no mesmo site
# disparam o bloqueio anti-bot (Turnstile) rapidamente.
_DOWNLOAD_LOCK = threading.Lock()


def is_challenge_html(low_html: str) -> bool:
    """True se o HTML parece uma pagina de bloqueio/challenge."""
    return any(hint in low_html for hint in CHALLENGE_HINTS)


def is_challenge_page(url: str, low_html: str) -> bool:
    """True se a pagina atual e um challenge do Cloudflare/Turnstile.

    O Cloudflare redireciona a navegacao para '/@waf/challenge': esse sinal
    na URL e mais rapido e confiavel que inspecionar o HTML, que so aparece
    depois do redirect. Cobre tambem a pagina de challenge ja renderizada.
    """
    return "/@waf/" in (url or "") or is_challenge_html(low_html or "")


def cooldown(progress_cb: ProgressCb, progress: int, seconds: int) -> None:
    """Pausa longa apos falha, em passos curtos: o progresso continua
    reportando (e o cancelamento da tarefa e percebido na hora)."""
    remaining = seconds
    while remaining > 0:
        step = min(COOLDOWN_STEP_S, remaining)
        progress_cb(progress, f"Capitulo falhou — esfriando o site: {remaining}s ate o proximo...")
        time.sleep(step)
        remaining -= step


def item_noun(kind: str) -> str:
    """Rotulo do item (capitulo/volume) nas mensagens de progresso."""
    return "Volume" if kind == "volume" else "Capitulo"


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
    supports_challenge = True

    def match(self, url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if "mangafire" in host:
            return True
        path = parsed.path or ""
        return bool(TITLE_PATH_RE.match(path)) or "/chapter/" in path or "/volume/" in path

    def get_info(self, url: str) -> dict:
        with browser.run(state_path=STATE_PATH) as context:
            page = self._new_page(context)
            try:
                return self._read_info(page, url)
            finally:
                page.close()

    def solve_challenge(self, url: str, progress_cb: ProgressCb) -> None:
        """Abre o Chromium headful para o usuario resolver o challenge.

        E o humano que resolve (o ScraperHub nao burla CAPTCHA). Os cookies
        resultantes (cf_clearance) sao salvos em STATE_PATH e reaproveitados
        pelos proximos contextos headless (get_info/download).
        """
        title_url = parse_title_url(url)
        with browser.run(headless=False, state_path=STATE_PATH) as context:
            page = self._new_page(context)
            try:
                self._await_human(page, title_url, progress_cb)
            finally:
                page.close()

    def _await_human(self, page: Page, title_url: str, progress_cb: ProgressCb) -> None:
        """Navega ate o titulo e espera o usuario resolver o challenge."""
        page.goto(title_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        if not is_challenge_page(page.url, page.content().lower()):
            progress_cb(100, "Nenhuma verificacao pendente. Tente analisar de novo.")
            return
        progress_cb(0, "Resolva a verificacao na janela do navegador que abriu...")
        deadline = time.monotonic() + CHALLENGE_WAIT_S
        while time.monotonic() < deadline:
            page.wait_for_timeout(CHALLENGE_POLL_MS)
            try:
                livre = not is_challenge_page(page.url, page.content().lower())
                if livre and page.query_selector(TITLE_ROW_SELECTOR):
                    progress_cb(100, "Verificacao concluida. Tente analisar de novo.")
                    return
            except Exception:  # noqa: BLE001 - pagina navegando: reavalia no proximo tick
                continue
            # batida do progresso: tambem detecta cancelamento da tarefa
            restante = int(deadline - time.monotonic())
            progress_cb(0, f"Aguardando a verificacao humana... ({restante}s)")
        raise ScraperError(
            "Tempo esgotado esperando a verificacao humana. Tente de novo."
        )

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
        # a UI manda ids de capitulo (puros) e de volume ("vol:{id}") na mesma
        # lista: separa para montar a fila com capitulos primeiro
        pedidos = [str(item_id) for item_id in item_ids]
        chapter_ids = [item_id for item_id in pedidos if not item_id.startswith(VOLUME_PREFIX)]
        volume_ids = [item_id for item_id in pedidos if item_id.startswith(VOLUME_PREFIX)]
        with browser.run(state_path=STATE_PATH) as context:
            page = self._new_page(context)
            try:
                info = self._read_info(page, title_url)
            finally:
                page.close()
            title = sanitize(str(info["title"]))
            chapters = select_ascending(info["items"], chapter_ids)
            volumes = select_ascending(info.get("volumes") or [], volume_ids)
            if not chapters and not volumes:
                raise ScraperError("Nenhum capitulo ou volume valido foi selecionado.")
            base = DOWNLOADS_DIR / title
            state = load_state(base)
            # nomes antigos usavam o indice da selecao (mudava entre rodadas):
            # renomeia para o numero real ANTES de decidir o que pular
            labels = {
                str(item["id"]): str(item["label"])
                for item in list(info["items"]) + list(info.get("volumes") or [])
            }
            if migrate_entries(base, state, lambda item_id: base / numbered_folder(labels[item_id])):
                save_state(base, state)
            jobs: list[tuple[str, dict]] = [("chapter", item) for item in chapters]
            jobs += [("volume", item) for item in volumes]
            total = len(jobs)
            falhas: list[str] = []
            consecutivas = 0
            for index, (kind, item) in enumerate(jobs, start=1):
                item_id = str(item["id"])
                label = str(item["label"])
                section = "volumes" if kind == "volume" else "chapters"
                noun = item_noun(kind)
                folder = base / numbered_folder(label)
                if is_complete(state, item_id, folder, section):
                    # ja baixado: pula SEM abrir a pagina (retomada sem rede)
                    progress_cb(
                        int(index / total * 100),
                        f"{noun} {label} ja baixado, pulando",
                    )
                    continue
                progress_cb(
                    int((index - 1) / total * 100),
                    f"Iniciando {noun.lower()} {label} ({index}/{total})",
                )
                if kind == "volume":
                    target_url = f"{title_url}/volume/{item_id[len(VOLUME_PREFIX):]}"
                else:
                    target_url = f"{title_url}/chapter/{item_id}"
                item_page = self._new_page(context)
                try:
                    falha = self._download_item(
                        item_page,
                        folder,
                        index,
                        item,
                        progress_cb,
                        options,
                        total,
                        target_url,
                        kind,
                    )
                finally:
                    item_page.close()
                if falha:
                    falhas.append(falha)
                    consecutivas += 1
                    if consecutivas >= MAX_CONSECUTIVE_FAILURES:
                        restantes = total - index
                        raise ScraperError(
                            f"{MAX_CONSECUTIVE_FAILURES} itens SEGUIDOS sem paginas. "
                            f"Abortados {restantes} restante(s) para nao piorar um "
                            "provavel bloqueio do site — espere alguns minutos e tente "
                            "de novo (os ja baixados sao pulados). "
                            f"Itens que falharam ({len(falhas)}): " + "; ".join(falhas)
                        )
                    # pausa adaptativa: sitio irritado -> esfriar antes do proximo
                    cooldown(
                        progress_cb,
                        int(index / total * 100),
                        CHAPTER_COOLDOWN_S,
                    )
                    continue
                consecutivas = 0
                record_done(state, item_id, folder, section)
                save_state(base, state)
                progress_cb(
                    int(index / total * 100),
                    f"Concluido {noun.lower()} {label} ({index}/{total})",
                )
                if index < total:
                    time.sleep(CHAPTER_GAP_S)
            if falhas:
                raise ScraperError(
                    f"{len(falhas)}/{total} item(ns) falharam: " + "; ".join(falhas)
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
            if is_challenge_page(page.url, page.content().lower()):
                # falhar rapido: esperar o seletor de capitulos num challenge
                # so gera um timeout generico e enganoso
                raise SiteBlocked(CAPTCHA_MESSAGE)
            page.wait_for_selector("h1", timeout=INFO_TIMEOUT_MS)
            page.wait_for_selector(TITLE_ROW_SELECTOR, timeout=INFO_TIMEOUT_MS)
            title = (page.inner_text("h1") or "").strip()
            cover_el = page.query_selector('meta[property="og:image"]') or page.query_selector("img.poster, .poster img")
            cover = cover_el.get_attribute("content") if cover_el and cover_el.get_attribute("content") else None
            rows = self._all_chapter_rows(page)
            volumes = self._read_volumes(page)
        except SiteBlocked:
            raise
        except Exception as exc:
            if is_challenge_page(page.url, page.content().lower()):
                raise SiteBlocked(CAPTCHA_MESSAGE) from exc
            raise ScraperError(f"Falha ao ler a pagina do manga: {exc}") from exc
        items = self._items(rows)
        if not items:
            raise ScraperError("Nenhum capitulo encontrado nesta pagina.")
        return {
            "title": title or "Manga sem titulo",
            "cover": cover,
            "items": items,
            "volumes": volumes,
        }

    def _read_volumes(self, page: Page) -> list[dict]:
        """Le a aba Volumes do toggle (mesma lista paginada dos capitulos).

        Os volumes sao opcionais: qualquer problema nessa aba NAO pode derrubar
        a listagem de capitulos, entao a falha vira lista vazia. Ao final o
        toggle volta para Chapters (higiene; a pagina e fechada logo depois).
        """
        if not self._click_tab(page, "Volumes"):
            return []
        try:
            volume_rows = self._all_chapter_rows(page, parse_volume_id)
        except Exception:  # noqa: BLE001 - aba opcional: capitulos ja bastam
            volume_rows = []
        self._click_tab(page, "Chapters")
        return self._volume_items(volume_rows)

    @staticmethod
    def _click_tab(page: Page, text: str) -> bool:
        """Clica no toggle Chapters/Volumes pelo texto; False se nao existir.

        O click e despachado via JS: overlays de anuncio do site interceptam
        pointer events e fazem o click nativo do Playwright estourar timeout.
        """
        return bool(
            page.evaluate(
                """(texto) => {
                    const els = Array.from(document.querySelectorAll('.title-detail__tab'));
                    const alvo = els.find(e => (e.innerText || '').trim().toLowerCase() === texto.toLowerCase());
                    if (!alvo) { return false; }
                    alvo.click();
                    return true;
                }""",
                text,
            )
        )

    def _all_chapter_rows(
        self,
        page: Page,
        id_parser: Callable[[str], str | None] = parse_chapter_id,
    ) -> list[dict]:
        """Coleta as rows de TODAS as paginas do npager (20 por pagina).

        Serve para capitulos e volumes: a aba Volumes usa a mesma lista
        paginada, e o `id_parser` decide qual id extrair do href.

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
                row_id = id_parser(str(row.get("href") or ""))
                if row_id and row_id not in seen:
                    seen.add(row_id)
                    all_rows.append(row)
            clicked = page.evaluate(
                """() => {
                    const btns = Array.from(document.querySelectorAll('.npager__num'));
                    const active = btns.find(b => b.classList.contains('is-active'));
                    const current = active ? parseInt(active.innerText, 10) : 0;
                    let target = null;
                    let targetNum = Infinity;
                    for (const b of btns) {
                        const n = parseInt(b.innerText.trim(), 10);
                        // proxima pagina sequencial: clicar o maior numero
                        // (ex.: 1 -> 5 com paginacao 1..5) pulava as do meio
                        if (!isNaN(n) && n > current && n < targetNum) { target = b; targetNum = n; }
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

    @staticmethod
    def _volume_items(rows: list[dict]) -> list[dict]:
        """Monta os itens de volume a partir das rows da aba Volumes.

        O rotulo nao usa o sub (ele traz "N chapters", a contagem de
        capitulos) — o numero vem do proprio "Vol. N" e a contagem vira o
        campo `count` (a UI mostra "Vol. N — M capitulos").
        """
        items: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            volume_id = parse_volume_id(str(row.get("href") or ""))
            if not volume_id or volume_id in seen:
                continue
            seen.add(volume_id)
            numero = str(row.get("num") or "").strip() or "Volume"
            flag = str(row.get("flag") or "")
            if flag:
                # mesmo volume em varios idiomas: sem a flag o usuario nao sabe
                # qual esta baixando
                label = f"{numero} [{flag}]"
            else:
                label = numero
            count = chapter_number(str(row.get("sub") or ""))
            items.append(
                {
                    "id": f"{VOLUME_PREFIX}{volume_id}",
                    "label": label,
                    "flag": flag,
                    "count": int(count) if count else 0,
                }
            )
        return order_items(items)

    def _download_item(
        self,
        page: Page,
        folder: Path,
        index: int,
        item: dict,
        progress_cb: ProgressCb,
        options: dict,
        total: int,
        target_url: str,
        kind: str,
    ) -> str | None:
        """Baixa um capitulo ou volume; retorna motivo de falha ou None se ok.

        O skip local (manifesto) e feito antes, em `_download_all`. Aqui
        permanece o skip por rede para bibliotecas ANTIGAS (sem manifesto):
        na primeira passada ele detecta o item completo, pula e o manifesto e
        gravado — as retomadas seguintes ja nao tocam a rede.
        """
        label = str(item["label"])
        noun = item_noun(kind)
        images: list[str] = []
        last_error: Exception | None = None
        for attempt in range(1, IMG_ATTEMPTS + 1):
            try:
                images = self._load_item_images(page, target_url, kind)
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
        if folder_pages(folder) == len(images):
            progress_cb(int((index - 1) / total * 100), f"{noun} {label} ja baixado, pulando")
            return None
        folder.mkdir(parents=True, exist_ok=True)
        for position, image_url in enumerate(images, start=1):
            data = browser.download_binary(page, image_url)
            extension = image_extension(image_url, data)
            (folder / f"{position:03d}{extension}").write_bytes(data)
            percent = int(((index - 1) + position / len(images)) / total * 100)
            progress_cb(percent, f"{noun[:3]} {label}/pg {position}")
            time.sleep(DELAY_S)
        if options.get("cbz"):
            make_cbz(folder)
        return None

    def _load_item_images(self, page: Page, target_url: str, kind: str = "chapter") -> list[str]:
        """Abre a pagina do capitulo/volume e coleta as imagens do reader.

        O reader do volume nao rola: e um swiper horizontal que so renderiza
        os slides proximos da posicao atual (lazy-load) e abre no FIM do
        volume (posicao de leitura salva no site). Entao o volume e coletado
        navegando com setas do teclado do primeiro ao ultimo slide.

        Levanta SiteBlocked imediatamente se a pagina for um challenge do
        Cloudflare/Turnstile (martelar os proximos itens so piora o bloqueio e
        o CAPTCHA nao e burlado).
        """
        page.goto(target_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        try:
            page.wait_for_selector(CHAPTER_IMG_SELECTOR, timeout=IMG_FIRST_TIMEOUT_MS)
        except Exception:
            if is_challenge_page(page.url, page.content().lower()):
                raise SiteBlocked(CAPTCHA_MESSAGE)
            # sem imagens em IMG_FIRST_TIMEOUT_MS: segue para o scroll/navegacao,
            # que cobre readers lentos/lazy
        if kind == "volume":
            images = self._sweep_volume_images(page)
        else:
            browser.scroll_until_stable(page, CHAPTER_IMG_SELECTOR, IMG_MAX_ITER, IMG_WAIT_MS)
            images = self._chapter_images(page)
        if not images and is_challenge_page(page.url, page.content().lower()):
            raise SiteBlocked(CAPTCHA_MESSAGE)
        return images

    def _sweep_volume_images(self, page: Page) -> list[str]:
        """Varre o swiper do volume do primeiro ao ultimo slide, coletando.

        O swiper mantem todos os slides no DOM, mas so instancia as imgs
        proximas da posicao ativa. Setas avancam o slide e disparam o
        lazy-load; coleta para de crescer por VOLUME_STALE_STEPS passos.
        """
        slides = page.eval_on_selector_all(".swiper-slide", "els => els.length")
        if not slides:
            return []
        # volta para o inicio (o reader abre onde o usuario parou: no fim)
        for _ in range(slides + 5):
            page.keyboard.press("ArrowLeft")
        coletadas: list[str] = []
        seen: set[str] = set()
        sem_novo = 0
        for _ in range(slides * 2 + 10):
            page.wait_for_timeout(IMG_STEP_WAIT_MS)
            novas = [url for url in self._chapter_images(page) if url not in seen]
            if novas:
                seen.update(novas)
                coletadas.extend(novas)
                sem_novo = 0
            else:
                sem_novo += 1
                if sem_novo >= VOLUME_STALE_STEPS:
                    break
            page.keyboard.press("ArrowRight")
        return coletadas

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

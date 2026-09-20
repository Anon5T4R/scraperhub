"""Busca de mangas por nome: MangaFire (sugestoes) + sites WordPress (?s=)."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from .scrapers.animestream_net import USER_AGENT
from .scrapers.base import app_root

SITES_FILE = app_root() / "manga-sites.txt"
SERIES_PATH_RE = re.compile(r"^/manga/[^/]+/?$")
MAX_RESULTS = 20
REQUEST_TIMEOUT = 20
SUGGESTION_LIMIT = 5


def default_sites() -> list[str]:
    """Sites de busca de mangas usados quando manga-sites.txt ainda nao existe."""
    return ["https://tsundoku.com.br/", "https://w2.chainsmokercat.website/"]


def load_sites() -> list[str]:
    """Le manga-sites.txt (uma URL por linha, ignora # e vazias); cria se faltar."""
    if not SITES_FILE.exists():
        return save_sites(default_sites())
    urls: list[str] = []
    for line in SITES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls or default_sites()


def save_sites(urls: list[str]) -> list[str]:
    """Valida, normaliza (com / final) e grava as URLs; retorna as salvas."""
    saved: list[str] = []
    for url in urls:
        url = url.strip()
        if not url or url.startswith("#"):
            continue
        parsed = urlparse(url if "://" in url else "https://" + url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            continue
        normalized = f"{parsed.scheme}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}/"
        if normalized not in saved:
            saved.append(normalized)
    SITES_FILE.write_text("\n".join(saved) + "\n", encoding="utf-8")
    return saved


def _search_mangafire(term: str) -> list[dict]:
    """Sugestoes do input de busca da home do MangaFire via Playwright.

    O dropdown traz ate 5 sugestoes; os itens de trending abaixo contem
    'ago' no texto (ex '12h ago') e marcam o fim das sugestoes.
    """
    from .scrapers import browser

    try:
        with browser.run(headless=True) as context:
            page = context.new_page()
            try:
                page.goto("https://mangafire.to/", timeout=45000, wait_until="domcontentloaded")
                campo = page.query_selector(
                    "input[type='search'], input[name*='search'], input[placeholder*='earch']"
                )
                if campo is None:
                    return []
                campo.fill(term)
                page.wait_for_timeout(3000)
                sugestoes = page.evaluate(
                    """() => Array.from(document.querySelectorAll('a[href*="/title/"]'))
                        .slice(0, 25)
                        .map(a => ({href: a.getAttribute('href') || '', text: (a.innerText || '').trim()}))"""
                )
            finally:
                page.close()
    except Exception:
        return []  # site fora/Captcha nao derruba a busca
    resultados: list[dict] = []
    for item in sugestoes:
        texto = str(item.get("text") or "")
        if "ago" in texto:
            break  # marcador de trending: sugestoes acabaram
        href = str(item.get("href") or "")
        if not href.startswith("/title/") or "/chapter/" in href:
            continue
        slug = href.rstrip("/").split("/")[-1]
        titulo = texto.splitlines()[0].strip() if texto else ""
        if len(titulo) < 3:
            titulo = slug.replace("-", " ").title()
        resultados.append(
            {
                "url": "https://mangafire.to" + href,
                "title": titulo,
                "idioma": "Ingles",
                "site": "mangafire.to",
            }
        )
        if len(resultados) >= SUGGESTION_LIMIT:
            break
    return resultados


def _search_wp(home: str, term: str) -> list[dict]:
    """Consulta {home}?s={term} e extrai os links de series de manga."""
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(follow_redirects=True, timeout=REQUEST_TIMEOUT, headers=headers) as client:
        response = client.get(home, params={"s": term})
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    hostname = urlparse(home).hostname or home
    found: list[dict] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        href = str(link.get("href") or "")
        absolute = urljoin(home, href)
        parsed = urlparse(absolute)
        if parsed.hostname != hostname:
            continue
        path = parsed.path
        if not SERIES_PATH_RE.match(path):
            continue
        slug = path.rstrip("/").split("/")[-1]
        if "cap-" in slug or "chapter" in slug:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        found.append(
            {
                "url": absolute,
                "title": _wp_title(link, slug),
                "idioma": "PT-BR",
                "site": hostname,
            }
        )
        if len(found) >= MAX_RESULTS:
            break
    return found


def _wp_title(link: Tag, slug: str) -> str:
    """Titulo do resultado: alt da capa, texto util do link ou slug."""
    image = link.find("img")
    alt = str(image.get("alt") or "").strip() if image else ""
    if len(alt) >= 4:
        return alt
    text = link.get_text(" ", strip=True)
    if len(text) >= 4 and "cap" not in text.lower():
        return text
    return slug.replace("-", " ").title()


def search_manga(term: str) -> tuple[list[dict], dict[str, str]]:
    """Busca mangas por nome: MangaFire primeiro, depois os sites WordPress.

    Filtra resultados irrelevantes (sites que retornam qualquer coisa),
    mas mantem a lista crua se o filtro remover tudo.
    """
    from .discovery import relevante

    results: list[dict] = []
    errors: dict[str, str] = {}
    seen: set[str] = set()
    for item in _search_mangafire(term):
        if item["url"] not in seen:
            seen.add(item["url"])
            results.append(item)
    sites = load_sites()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_search_wp, site, term): site for site in sites}
        for future, site in futures.items():
            try:
                found = future.result()
            except Exception as exc:  # site fora do ar nao derruba os demais
                errors[urlparse(site).hostname or site] = str(exc)[:150]
                continue
            for item in found:
                if item["url"] not in seen:
                    seen.add(item["url"])
                    results.append(item)
    relevantes = [
        r for r in results if relevante(f"{r.get('title', '')} {r.get('url', '')}", term)
    ]
    return (relevantes or results), errors

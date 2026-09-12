"""Busca multi-site de animes e verificacao de qualidade das fontes."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from .scrapers import detect
from .scrapers.animestream_net import USER_AGENT, SilentLogger
from .scrapers.base import app_root

SITES_FILE = app_root() / "sites.txt"
ANIME_PATH_RE = re.compile(r"^/anime/(?:a/)?[^/]+")
MAX_RESULTS = 20
REQUEST_TIMEOUT = 20
LANGUAGE_PADRAO = "Legendado (padrao do site)"
_QUALITY_CACHE: dict[str, str] = {}


def default_sites() -> list[str]:
    """Sites de busca usados quando sites.txt ainda nao existe."""
    return ["https://animeq.cloud/", "https://animesdigital.org/"]


def load_sites() -> list[str]:
    """Le sites.txt (uma URL por linha, ignora # e vazias); cria se faltar."""
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


def search_all(term: str) -> tuple[list[dict], dict[str, str]]:
    """Busca o termo em todos os sites; retorna (resultados, erros por host).

    Filtra resultados irrelevantes (sites que retornam qualquer coisa),
    mas mantem a lista crua se o filtro remover tudo.
    """
    from .discovery import relevante

    sites = load_sites()
    results: list[dict] = []
    errors: dict[str, str] = {}
    seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_search_site, site, term): site for site in sites}
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


def _search_site(home: str, term: str) -> list[dict]:
    """Consulta {home}?s={term} e extrai os links de anime encontrados."""
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(follow_redirects=True, timeout=REQUEST_TIMEOUT, headers=headers) as client:
        response = client.get(home, params={"s": term})
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    site = urlparse(home).hostname or home
    found: list[dict] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        href = str(link.get("href") or "")
        absolute = urljoin(home, href)
        path = urlparse(absolute).path
        if not ANIME_PATH_RE.match(path) or absolute in seen:
            continue
        seen.add(absolute)
        title = _link_title(link, absolute)
        found.append(
            {
                "url": absolute,
                "title": title,
                "idioma": _idioma(f"{path} {title}"),
                "site": site,
            }
        )
        if len(found) >= MAX_RESULTS:
            break
    return found


def _link_title(link: Tag, url: str) -> str:
    """Titulo do resultado: alt da capa, texto util do link ou slug."""
    image = link.find("img")
    alt = str(image.get("alt") or "").strip() if image else ""
    if len(alt) >= 4:
        return alt
    text = link.get_text(" ", strip=True)
    if len(text) >= 4 and text.lower() not in ("tv", "hd", "ler", "ver"):
        return text
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").title()


def _idioma(text: str) -> str:
    """Detecta o idioma pelo slug/titulo; fallback para o padrao do site."""
    low = text.lower()
    if "dublado" in low:
        return "Dublado"
    if any(m in low for m in ("espanol", "español", "latino", "sub es")):
        return "Espanhol"
    if any(m in low for m in ("english", "sub eng", "eng sub", "subbed")):
        return "Ingles"
    return LANGUAGE_PADRAO


def verify_quality(url: str) -> dict:
    """Verifica a melhor qualidade do primeiro episodio da serie."""
    scraper = detect(url)
    if scraper is None:
        return {"suporte": False, "motivo": "Nenhum scraper reconheceu esta URL."}
    if scraper.kind != "video":
        return {"suporte": False, "motivo": "verificacao disponivel apenas para series"}
    if not hasattr(scraper, "first_source"):
        return {"suporte": False, "motivo": "verificacao disponivel apenas para series de anime"}
    try:
        info = scraper.get_info(url)
        items = info.get("items") or []
        if not items:
            return {"suporte": False, "motivo": "Nenhum episodio encontrado."}
        source = scraper.first_source(str(items[0]["id"]))
        if not source:
            return {"suporte": False, "motivo": "Nenhuma fonte de video encontrada."}
        title = str(info.get("title") or "Sem titulo")
        return {
            "suporte": True,
            "title": title,
            "episodios": len(items),
            "qualidade": probe_quality(source),
            "idioma": _idioma(f"{url} {title}"),
        }
    except Exception as exc:
        return {"suporte": False, "motivo": str(exc)[:150]}


def probe_quality(source: str) -> str:
    """Maior resolucao (altura) entre os formatos reportados pelo yt-dlp."""
    if source in _QUALITY_CACHE:
        return _QUALITY_CACHE[source]
    import time

    import yt_dlp

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "nocheckcertificate": True,
        "logger": SilentLogger(),
    }
    info = None
    for attempt in range(2):  # SSL/5xx transitivos: uma retentativa
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(source, download=False)
            break
        except Exception:
            if attempt:
                result = "desconhecida"
                _QUALITY_CACHE[source] = result
                return result
            time.sleep(2)
    formats = (info or {}).get("formats") or []
    heights = [int(f["height"]) for f in formats if f.get("height")]
    if heights:
        result = f"{max(heights)}p"
    else:
        # playlist unica sem resolucao publicada (comum nesses CDNs);
        # o download pega sempre a unica faixa disponivel
        result = "unica"
    _QUALITY_CACHE[source] = result
    return result

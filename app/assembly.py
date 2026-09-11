"""Montagem de temporada multi-fonte: melhor fonte por episodio, com fallback."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from .scrapers.animestream import AnimeStreamScraper
from .scrapers.animestream_net import run_downloads
from .scrapers.base import ProgressCb, ScraperError
from .search import _quality, search_all

MAX_FONTES = 4
_SCRAPER = AnimeStreamScraper()


def _label_num(label: str) -> int | None:
    """Ultimo numero inteiro do rotulo ('Ep 03' e 'S1E03' -> 3), se houver."""
    numeros = re.findall(r"\d+", label)
    return int(numeros[-1]) if numeros else None


def _canonical(label: str) -> str:
    """Chave unica do episodio: 'Ep 03' e 'S1E03' viram 'Ep 03'."""
    numero = _label_num(label)
    if numero is not None:
        return f"Ep {numero:02d}"
    return label.strip().lower()


def _label_key(label: str) -> tuple[int, int, str]:
    """Numeros em ordem crescente; rotulos nao numericos ('Ep trailer') por ultimo."""
    numero = _label_num(label)
    if numero is None:
        return (1, 0, label)
    return (0, numero, label)


def _quality_score(qualidade: str | None) -> int:
    """1080p > 720p > unica > desconhecida > fonte sem primeira linha valida."""
    if not qualidade:
        return -1
    match = re.match(r"(\d+)p", qualidade)
    if match:
        return int(match.group(1))
    return 1 if qualidade == "unica" else 0


def _first_ep(eps: dict[str, str]) -> str | None:
    """URL do episodio de menor numero (ou o primeiro, se nao houver numero)."""
    if not eps:
        return None
    numerados = [(n, url) for label, url in eps.items() if (n := _label_num(label)) is not None]
    if numerados:
        return min(numerados, key=lambda par: par[0])[1]
    return next(iter(eps.values()))


def _probe(result: dict) -> dict:
    """Coleta eps e qualidade de uma fonte; erro individual nao aborta o plano."""
    url = str(result.get("url") or "")
    site = str(result.get("site") or urlparse(url).hostname or "")
    fonte = {
        "site": site,
        "url": url,
        "idioma": str(result.get("idioma") or ""),
        "title": "",
        "eps": {},
        "qualidade": None,
    }
    try:
        info = _SCRAPER.get_info(url)
    except Exception as exc:
        fonte["erro"] = str(exc)[:150]
        return fonte
    items = info.get("items") or []
    # normaliza os rotulos por chave canonica: 'Ep 3' e 'S1E03' sao o mesmo ep
    eps: dict[str, str] = {}
    for item in items:
        chave = _canonical(str(item["label"]))
        eps.setdefault(chave, str(item["id"]))
    fonte["eps"] = eps
    fonte["title"] = str(info.get("title") or "")
    first = _first_ep(fonte["eps"])
    if first:
        try:
            source = _SCRAPER.first_source(first)
        except Exception:
            source = None  # fonte sem primeira linha valida: prioridade menor
        if source:
            fonte["qualidade"] = _quality(source)
    return fonte


def plan_season(term: str, idioma: str = "qualquer") -> dict:
    """Monta a temporada: fontes rankeadas e a melhor fonte por episodio."""
    resultados, _ = search_all(term)
    fontes = [r for r in resultados if _SCRAPER.match(str(r.get("url") or ""))]
    if idioma and idioma.lower() != "qualquer":
        alvo = idioma.lower()
        fontes = [r for r in fontes if alvo in str(r.get("idioma") or "").lower()]
    # dedupe por URL e diversidade: max 2 por site (round-robin), para um
    # site com muitas variantes nao ocupar todas as vagas antes dos demais
    unicos: list[dict] = []
    vistos: set[str] = set()
    por_site: dict[str, int] = {}
    rodada = 0
    while len(unicos) < MAX_FONTES:
        adicionou = False
        for r in fontes:
            url = str(r.get("url") or "")
            site = str(r.get("site") or "")
            chave = f"{site}|{url}"
            if chave in vistos or por_site.get(site, 0) >= 2:
                continue
            if url in vistos:
                continue
            vistos.add(chave)
            vistos.add(url)
            por_site[site] = por_site.get(site, 0) + 1
            unicos.append(r)
            adicionou = True
            if len(unicos) >= MAX_FONTES:
                break
        if not adicionou:
            break
        rodada += 1
    fontes = unicos[:MAX_FONTES]
    with ThreadPoolExecutor(max_workers=MAX_FONTES) as pool:
        coletadas = list(pool.map(_probe, fontes))
    ordem = sorted(
        range(len(coletadas)),
        key=lambda i: (-_quality_score(coletadas[i]["qualidade"]), -len(coletadas[i]["eps"]), i),
    )
    rankeadas = [coletadas[i] for i in ordem]
    labels = {label for fonte in coletadas for label in fonte["eps"]}
    episodios: list[dict] = []
    for label in sorted(labels, key=_label_key):
        donas = [f for f in rankeadas if label in f["eps"]]
        candidatos = [
            {"site": f["site"], "url": f["eps"][label], "qualidade": f["qualidade"]}
            for f in donas
        ]
        episodios.append(
            {
                "label": label,
                "escolhido": candidatos[0] if candidatos else None,
                "alternativas": candidatos[1:],
            }
        )
    return {
        "fontes": [
            {
                "site": f["site"],
                "url": f["url"],
                "idioma": f["idioma"],
                "title": f["title"],
                "eps_total": len(f["eps"]),
                "qualidade": f["qualidade"],
                **({"erro": f["erro"]} if "erro" in f else {}),
            }
            for f in coletadas
        ],
        "episodios": episodios,
    }


def download_season(
    term: str,
    idioma: str,
    wanted: list[str] | None,
    progress_cb: ProgressCb,
    options: dict | None = None,
) -> None:
    """Baixa a temporada montada, com fallback por episodio e relatorio de procedencia."""
    plan = plan_season(term, idioma)
    episodios = plan["episodios"]
    if wanted:
        pedidos = set(wanted)
        episodios = [ep for ep in episodios if ep["label"] in pedidos]
    if not episodios:
        raise ScraperError("Nenhum episodio para baixar nesta temporada.")
    title = term
    for fonte in plan["fontes"]:
        if fonte.get("title") and fonte.get("eps_total") and not fonte.get("erro"):
            title = str(fonte["title"])
            break
    by_label = {ep["label"]: ep for ep in episodios}
    provenance: dict[str, dict] = {}

    def download_one(_item_id: str, label: str) -> None:
        episode = by_label[label]
        candidatos: list[dict] = []
        if episode.get("escolhido"):
            candidatos.append(episode["escolhido"])
        candidatos.extend(episode.get("alternativas") or [])
        if not candidatos:
            provenance[label] = {"label": label, "fonte": None, "erro": "sem fonte"}
            raise ScraperError(f"{label}: nenhuma fonte disponivel")
        erros: list[str] = []
        for candidato in candidatos:
            try:
                _SCRAPER.download_episode(candidato["url"], title, label, progress_cb)
            except ScraperError as exc:
                erros.append(f"{candidato['site']}: {str(exc)[-60:]}")
                continue
            provenance[label] = {
                "label": label,
                "fonte": candidato["site"],
                "qualidade": candidato.get("qualidade"),
            }
            return
        provenance[label] = {"label": label, "fonte": None, "erro": "; ".join(erros)}
        raise ScraperError(f"{label} falhou em todas as fontes")

    selected = [{"id": ep["label"], "label": ep["label"]} for ep in episodios]
    falhou = False
    try:
        run_downloads(selected, download_one, progress_cb)
    except ScraperError:
        falhou = True  # baixados ficam salvos; resumo e levantado no final
    linhas: list[str] = []
    for ep in episodios:
        prov = provenance.get(ep["label"]) or {}
        if prov.get("fonte"):
            qualidade = prov.get("qualidade")
            sufixo = f" ({qualidade})" if qualidade else ""
            linhas.append(f"{ep['label']} <- {prov['fonte']}{sufixo}")
        else:
            linhas.append(f"{ep['label']} FALHOU em todas as fontes")
    for linha in linhas:
        progress_cb(100, linha)
    if falhou:
        raise ScraperError("Resumo da temporada: " + "; ".join(linhas))

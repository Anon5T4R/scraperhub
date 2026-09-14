"""Estado local de download por titulo (permite retomar sem tocar na rede).

O manifesto fica em `downloads/<titulo>/_estado.json` e registra, por capitulo,
a pasta e quantas paginas foram gravadas. No retry, um capitulo marcado como
concluido e com a contagem batendo e pulado SEM abrir a pagina dele — evita
re-baixar/recarregar o que ja deu certo e evita morrer num challenge num
capitulo que ja estava pronto.

O manifesto e um atalho: a verdade continua sendo os arquivos em disco. Se o
manifesto faltar (biblioteca antiga), a checagem por rede de sempre acontece
uma vez e o manifesto e populado.
"""
from __future__ import annotations

import json
from pathlib import Path

STATE_FILENAME = "_estado.json"


def state_path(base: Path) -> Path:
    """Caminho do manifesto dentro da pasta do titulo."""
    return base / STATE_FILENAME


def load_state(base: Path) -> dict:
    """Le o manifesto; devolve estrutura vazia se faltar ou estiver invalido."""
    try:
        data = json.loads(state_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"chapters": {}}
    if not isinstance(data, dict) or not isinstance(data.get("chapters"), dict):
        return {"chapters": {}}
    return {"chapters": data["chapters"]}


def save_state(base: Path, state: dict) -> None:
    """Grava o manifesto de forma atomica (tmp + replace)."""
    base.mkdir(parents=True, exist_ok=True)
    path = state_path(base)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def folder_pages(folder: Path) -> int:
    """Numero de arquivos (paginas) ja gravados na pasta do capitulo."""
    if not folder.is_dir():
        return 0
    return sum(1 for entry in folder.iterdir() if entry.is_file())


def is_complete(state: dict, chapter_id: str, folder: Path) -> bool:
    """True se o capitulo esta no manifesto como concluido e a contagem bate."""
    entry = (state.get("chapters") or {}).get(str(chapter_id))
    if not isinstance(entry, dict) or not entry.get("done"):
        return False
    expected = entry.get("pages")
    if not expected:
        return False
    return folder_pages(folder) == int(expected)


def record_done(state: dict, chapter_id: str, folder: Path) -> int:
    """Marca o capitulo como concluido no manifesto; devolve as paginas."""
    pages = folder_pages(folder)
    state.setdefault("chapters", {})[str(chapter_id)] = {
        "folder": folder.name,
        "pages": pages,
        "done": True,
    }
    return pages

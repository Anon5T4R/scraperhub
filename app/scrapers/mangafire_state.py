"""Estado local de download por titulo (permite retomar sem tocar na rede).

O manifesto fica em `downloads/<titulo>/_estado.json` e registra, por capitulo
(ou volume), a pasta e quantas paginas foram gravadas. No retry, um item
marcado como concluido e com a contagem batendo e pulado SEM abrir a pagina
dele — evita re-baixar/recarregar o que ja deu certo e evita morrer num
challenge num item que ja estava pronto.

O manifesto e um atalho: a verdade continua sendo os arquivos em disco. Se o
manifesto faltar (biblioteca antiga), a checagem por rede de sempre acontece
uma vez e o manifesto e populado.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

STATE_FILENAME = "_estado.json"
# O manifesto guarda capitulos e volumes em secoes separadas, com a mesma
# estrutura por item: {"folder", "pages", "done"}.
SECTIONS = ("chapters", "volumes")


def state_path(base: Path) -> Path:
    """Caminho do manifesto dentro da pasta do titulo."""
    return base / STATE_FILENAME


def load_state(base: Path) -> dict:
    """Le o manifesto; devolve estrutura vazia se faltar ou estiver invalido."""
    vazio = {"chapters": {}, "volumes": {}}
    try:
        data = json.loads(state_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return vazio
    if not isinstance(data, dict) or not isinstance(data.get("chapters"), dict):
        return vazio
    volumes = data.get("volumes")
    return {
        "chapters": data["chapters"],
        "volumes": volumes if isinstance(volumes, dict) else {},
    }


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


def is_complete(state: dict, chapter_id: str, folder: Path, section: str = "chapters") -> bool:
    """True se o item esta no manifesto como concluido e a contagem bate.

    A pasta computada pode nao bater com a gravada (biblioteca antiga, quando
    o nome usava o indice da selecao): nesse caso a pasta registrada no
    manifesto e a fonte de verdade ate a migracao para o nome pelo numero.
    """
    entry = (state.get(section) or {}).get(str(chapter_id))
    if not isinstance(entry, dict) or not entry.get("done"):
        return False
    expected = entry.get("pages")
    if not expected:
        return False
    if folder_pages(folder) == int(expected):
        return True
    recorded = str(entry.get("folder") or "")
    if not recorded:
        return False
    return folder_pages(folder.parent / recorded) == int(expected)


def record_done(state: dict, chapter_id: str, folder: Path, section: str = "chapters") -> int:
    """Marca o item como concluido no manifesto; devolve as paginas."""
    pages = folder_pages(folder)
    state.setdefault(section, {})[str(chapter_id)] = {
        "folder": folder.name,
        "pages": pages,
        "done": True,
    }
    return pages


def migrate_entries(base: Path, state: dict, folder_for: Callable[[str], Path]) -> int:
    """Renomeia pastas antigas (nome pelo indice) para o nome pelo numero.

    So mexe em entradas concluidas cuja pasta gravada ainda existe. Se o
    destino ja existir, mantem a pasta antiga (nao sobrescreve nada); se
    `folder_for` nao souber o caminho novo (item fora da lista atual), a
    entrada fica como esta. Retorna quantas pastas migraram.
    """
    migrated = 0
    for section in SECTIONS:
        entries = state.get(section)
        if not isinstance(entries, dict):
            continue
        for chapter_id, entry in entries.items():
            if not isinstance(entry, dict) or not entry.get("done"):
                continue
            old_name = str(entry.get("folder") or "")
            if not old_name:
                continue
            old_folder = base / old_name
            if not old_folder.is_dir():
                continue
            try:
                new_folder = folder_for(str(chapter_id))
            except (KeyError, ValueError):
                continue
            if new_folder.name == old_name or new_folder.exists():
                continue
            old_folder.rename(new_folder)
            entry["folder"] = new_folder.name
            migrated += 1
    return migrated

"""Testes do manifesto de estado do mangafire (retomada sem rede)."""
from app.scrapers.mangafire_state import (
    folder_pages,
    is_complete,
    load_state,
    record_done,
    save_state,
)


def test_load_state_ausente(tmp_path):
    assert load_state(tmp_path) == {"chapters": {}}


def test_save_load_roundtrip(tmp_path):
    folder = tmp_path / "001_Ch_1"
    folder.mkdir()
    (folder / "001.webp").write_bytes(b"x")
    state = {"chapters": {}}
    record_done(state, "abc", folder)
    save_state(tmp_path, state)
    loaded = load_state(tmp_path)
    assert loaded["chapters"]["abc"]["pages"] == 1
    assert loaded["chapters"]["abc"]["folder"] == "001_Ch_1"


def test_is_complete_sem_entrada(tmp_path):
    folder = tmp_path / "001_Ch_1"
    folder.mkdir()
    (folder / "001.webp").write_bytes(b"x")
    assert is_complete({"chapters": {}}, "abc", folder) is False


def test_is_complete_bate(tmp_path):
    folder = tmp_path / "001_Ch_1"
    folder.mkdir()
    (folder / "001.webp").write_bytes(b"x")
    (folder / "002.webp").write_bytes(b"x")
    state = {"chapters": {}}
    record_done(state, "abc", folder)
    assert is_complete(state, "abc", folder) is True
    # conteudo mudou (pagina removida) -> deixa de estar completo
    (folder / "002.webp").unlink()
    assert is_complete(state, "abc", folder) is False


def test_is_complete_falta_pasta(tmp_path):
    state = {"chapters": {"abc": {"folder": "x", "pages": 2, "done": True}}}
    assert is_complete(state, "abc", tmp_path / "nao-existe") is False


def test_folder_pages(tmp_path):
    assert folder_pages(tmp_path / "nada") == 0
    folder = tmp_path / "cap"
    folder.mkdir()
    (folder / "001.webp").write_bytes(b"x")
    assert folder_pages(folder) == 1

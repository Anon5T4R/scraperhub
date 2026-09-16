"""Testes do manifesto de estado do mangafire (retomada sem rede)."""
from app.scrapers.mangafire_state import (
    folder_pages,
    is_complete,
    load_state,
    migrate_entries,
    record_done,
    save_state,
)


def test_load_state_ausente(tmp_path):
    assert load_state(tmp_path) == {"chapters": {}, "volumes": {}}


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


def test_save_load_roundtrip_volumes(tmp_path):
    folder = tmp_path / "0028_Vol_28_[en]"
    folder.mkdir()
    (folder / "001.webp").write_bytes(b"x")
    state = {"chapters": {}, "volumes": {}}
    record_done(state, "vol:78", folder, "volumes")
    save_state(tmp_path, state)
    loaded = load_state(tmp_path)
    assert loaded["chapters"] == {}
    assert loaded["volumes"]["vol:78"]["pages"] == 1
    assert loaded["volumes"]["vol:78"]["folder"] == "0028_Vol_28_[en]"


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


def test_is_complete_usa_pasta_gravada_no_manifesto(tmp_path):
    # biblioteca antiga: a pasta gravada tem o nome pelo indice; a computada
    # (pelo numero real) ainda nao existe — o manifesto e a fonte de verdade
    antiga = tmp_path / "001_Ch_166"
    antiga.mkdir()
    (antiga / "001.webp").write_bytes(b"x")
    state = {"chapters": {"abc": {"folder": "001_Ch_166", "pages": 1, "done": True}}}
    assert is_complete(state, "abc", tmp_path / "0166_Ch_166") is True


def test_is_complete_por_secao(tmp_path):
    folder = tmp_path / "0028_Vol_28_[en]"
    folder.mkdir()
    (folder / "001.webp").write_bytes(b"x")
    state = {"chapters": {}, "volumes": {}}
    record_done(state, "vol:78", folder, "volumes")
    assert is_complete(state, "vol:78", folder, "volumes") is True
    assert is_complete(state, "vol:78", folder) is False


def test_folder_pages(tmp_path):
    assert folder_pages(tmp_path / "nada") == 0
    folder = tmp_path / "cap"
    folder.mkdir()
    (folder / "001.webp").write_bytes(b"x")
    assert folder_pages(folder) == 1


def test_migrate_entries_renomeia(tmp_path):
    antiga = tmp_path / "001_Ch_1"
    antiga.mkdir()
    (antiga / "001.webp").write_bytes(b"x")
    state = {"chapters": {"abc": {"folder": "001_Ch_1", "pages": 1, "done": True}}}
    assert migrate_entries(tmp_path, state, lambda _id: tmp_path / "0001_Ch_1") == 1
    assert not antiga.exists()
    assert (tmp_path / "0001_Ch_1").is_dir()
    assert state["chapters"]["abc"]["folder"] == "0001_Ch_1"


def test_migrate_entries_nome_igual_nao_conta(tmp_path):
    pasta = tmp_path / "0001_Ch_1"
    pasta.mkdir()
    (pasta / "001.webp").write_bytes(b"x")
    state = {"chapters": {"abc": {"folder": "0001_Ch_1", "pages": 1, "done": True}}}
    assert migrate_entries(tmp_path, state, lambda _id: tmp_path / "0001_Ch_1") == 0
    assert pasta.is_dir()


def test_migrate_entries_conflito_mantem_antiga(tmp_path):
    antiga = tmp_path / "001_Ch_1"
    antiga.mkdir()
    (antiga / "001.webp").write_bytes(b"x")
    destino = tmp_path / "0001_Ch_1"
    destino.mkdir()
    state = {"chapters": {"abc": {"folder": "001_Ch_1", "pages": 1, "done": True}}}
    assert migrate_entries(tmp_path, state, lambda _id: destino) == 0
    assert antiga.is_dir()
    assert state["chapters"]["abc"]["folder"] == "001_Ch_1"


def test_migrate_entries_ignora_sem_done(tmp_path):
    antiga = tmp_path / "001_Ch_1"
    antiga.mkdir()
    state = {"chapters": {"abc": {"folder": "001_Ch_1", "pages": 0, "done": False}}}
    assert migrate_entries(tmp_path, state, lambda _id: tmp_path / "0001_Ch_1") == 0
    assert antiga.is_dir()
    assert state["chapters"]["abc"]["folder"] == "001_Ch_1"


def test_migrate_entries_ignora_pasta_ausente(tmp_path):
    state = {"chapters": {"abc": {"folder": "001_Ch_1", "pages": 1, "done": True}}}
    assert migrate_entries(tmp_path, state, lambda _id: tmp_path / "0001_Ch_1") == 0


def test_migrate_entries_ignora_desconhecido(tmp_path):
    antiga = tmp_path / "001_Ch_1"
    antiga.mkdir()
    state = {"chapters": {"abc": {"folder": "001_Ch_1", "pages": 1, "done": True}}}

    def folder_for(item_id: str):
        raise KeyError(item_id)

    assert migrate_entries(tmp_path, state, folder_for) == 0
    assert antiga.is_dir()
    assert state["chapters"]["abc"]["folder"] == "001_Ch_1"


def test_migrate_entries_volumes(tmp_path):
    antiga = tmp_path / "001_Vol_28"
    antiga.mkdir()
    (antiga / "001.webp").write_bytes(b"x")
    state = {"chapters": {}, "volumes": {"vol:78": {"folder": "001_Vol_28", "pages": 1, "done": True}}}
    assert migrate_entries(tmp_path, state, lambda _id: tmp_path / "0028_Vol_28_[en]") == 1
    assert state["volumes"]["vol:78"]["folder"] == "0028_Vol_28_[en]"
    assert not antiga.exists()

"""Testes das funcoes puras de parsing do scraper MangaFire."""
from app.scrapers.mangafire_parse import (
    TITLE_PATH_RE,
    chapter_label,
    image_extension,
    numbered_folder,
    order_items,
    parse_chapter_id,
    parse_title_url,
    parse_volume_id,
    sanitize,
    select_ascending,
)


def test_parse_chapter_id():
    assert parse_chapter_id("/title/slug/chapter/123") == "123"
    assert parse_chapter_id("https://mangafire.to/title/slug/chapter/456?page=2") == "456"


def test_parse_chapter_id_sem_capitulo():
    assert parse_chapter_id("/title/slug") is None
    assert parse_chapter_id("") is None


def test_parse_volume_id():
    assert parse_volume_id("/title/slug/volume/78") == "78"
    assert parse_volume_id("https://mangafire.to/title/slug/volume/1671?page=2") == "1671"


def test_parse_volume_id_sem_volume():
    assert parse_volume_id("/title/slug/chapter/1") is None
    assert parse_volume_id("/title/slug") is None
    assert parse_volume_id("") is None


def test_chapter_label_completo():
    assert chapter_label("270.1", "subtitulo") == "270.1 — subtitulo"


def test_chapter_label_parcial():
    assert chapter_label("270.1", "") == "270.1"
    assert chapter_label("", "subtitulo") == "subtitulo"


def test_chapter_label_vazio():
    assert chapter_label("", "") == "Capitulo"


def test_chapter_label_trim():
    assert chapter_label(" 270.1 ", " sub ") == "270.1 — sub"


def test_order_items_descendente():
    items = [
        {"label": "Ch. 1", "id": "a"},
        {"label": "Ch. 3", "id": "b"},
        {"label": "Ch. 2", "id": "c"},
    ]
    assert [i["id"] for i in order_items(items)] == ["b", "c", "a"]


def test_order_items_sem_numeros_mantem_ordem():
    items = [{"label": "Extra", "id": "a"}, {"label": "Bonus", "id": "b"}]
    assert order_items(items) == items


def test_order_items_vazio():
    assert order_items([]) == []


def test_order_items_misto_mantem_ordem():
    items = [{"label": "Ch. 1", "id": "a"}, {"label": "Extra", "id": "b"}]
    assert order_items(items) == items


def test_select_ascending():
    items = [
        {"label": "Ch. 3", "id": "c"},
        {"label": "Ch. 1", "id": "a"},
        {"label": "Ch. 2", "id": "b"},
    ]
    assert [i["id"] for i in select_ascending(items, ["b", "a"])] == ["a", "b"]


def test_select_ascending_sem_numeros_inverte():
    items = [{"label": "Extra", "id": "a"}, {"label": "Bonus", "id": "b"}]
    assert [i["id"] for i in select_ascending(items, ["a", "b"])] == ["b", "a"]


def test_select_ascending_ids_inexistentes():
    items = [{"label": "Ch. 1", "id": "a"}]
    assert select_ascending(items, ["zzz"]) == []


def test_sanitize_caracteres_invalidos():
    assert sanitize('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"


def test_sanitize_trim():
    assert sanitize("  nome  ") == "nome"


def test_sanitize_vazio():
    assert sanitize("") == "sem-nome"
    assert sanitize("...") == "sem-nome"


def test_image_extension_pela_url():
    assert image_extension("https://x.com/a.jpg", b"") == ".jpg"
    assert image_extension("https://x.com/a.jpeg", b"") == ".jpg"
    assert image_extension("https://x.com/a.png?w=100", b"") == ".png"
    assert image_extension("https://x.com/a.webp", b"") == ".webp"


def test_image_extension_sniff_bytes():
    assert image_extension("https://x.com/a", b"\xff\xd8\xff\xe0") == ".jpg"
    assert image_extension("https://x.com/a", b"\x89PNG\r\n\x1a\n") == ".png"
    assert image_extension("https://x.com/a", b"RIFF\x00\x00\x00\x00WEBP") == ".webp"


def test_image_extension_desconhecida_padrao_jpg():
    assert image_extension("https://x.com/a", b"dados desconhecidos") == ".jpg"


def test_numbered_folder_numero_real():
    assert numbered_folder("Ch. 270.1") == "0270.1_Ch_270.1"
    assert numbered_folder("Ch. 255 — x [en]") == "0255_Ch_255_—_x_[en]"


def test_numbered_folder_decimal():
    assert numbered_folder("Ch. 222.5 — y [en]") == "0222.5_Ch_222.5_—_y_[en]"


def test_numbered_folder_volume():
    assert numbered_folder("Vol. 28 [en]") == "0028_Vol_28_[en]"
    assert numbered_folder("Vol. 28") == "0028_Vol_28"


def test_numbered_folder_sem_numero():
    assert numbered_folder("Extra") == "Extra"
    assert numbered_folder("") == "sem-nome"


def test_parse_title_url():
    assert parse_title_url("https://mangafire.to/title/slug") == "https://mangafire.to/title/slug"
    assert parse_title_url("https://mangafire.to/title/slug/") == "https://mangafire.to/title/slug"


def test_parse_title_url_de_capitulo():
    assert (
        parse_title_url("https://mangafire.to/title/slug/chapter/123")
        == "https://mangafire.to/title/slug"
    )
    assert (
        parse_title_url("https://mangafire.to/title/slug/chapter/123?page=2")
        == "https://mangafire.to/title/slug"
    )


def test_parse_title_url_de_volume():
    assert (
        parse_title_url("https://mangafire.to/title/slug/volume/78")
        == "https://mangafire.to/title/slug"
    )
    assert (
        parse_title_url("https://mangafire.to/title/slug/volume/78?page=2")
        == "https://mangafire.to/title/slug"
    )


def test_title_path_re():
    assert TITLE_PATH_RE.match("/title/slug")
    assert TITLE_PATH_RE.match("/title/slug/")
    assert TITLE_PATH_RE.match("/TITLE/Slug")


def test_title_path_re_nao_casa():
    assert TITLE_PATH_RE.match("/title/slug/chapter/1") is None
    assert TITLE_PATH_RE.match("/other/slug") is None
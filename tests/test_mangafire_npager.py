"""Teste do clique sequencial do npager (regressao do bug v1.9.2).

O bug: o JS de paginacao clicava o MAIOR numero disponivel (ex.: 1 -> 5 com
paginacao "1 2 3 4 5 ... 40"), pulando as paginas do meio. Aqui rodamos o
MESMO snippet de clique usado por `_all_chapter_rows` (a constante PAGER_JS)
num HTML estatico que simula o npager com ellipsis e re-renderiza os botoes
e as rows a cada clique. A sequencia visitada tem que ser 1..40, sem pulos.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.scrapers.mangafire import PAGER_JS

TOTAL_PAGINAS = 40


def _chromium_disponivel() -> bool:
    """True se o Chromium (canal 'chromium') do Playwright esta instalado.

    Checa o executavel sem dar launch (launch e caro): o canal 'chromium'
    usa exatamente esse binario, entao sua ausencia implica skip.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).is_file()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _chromium_disponivel(),
    reason="Chromium do Playwright nao instalado",
)

# Fixture estatica: npager "1 2 3 4 5 ... 40" + lista de rows. O `go(n)` troca a
# pagina ativa e re-renderiza botoes/rows, simulando o re-render do site.
FIXTURE_HTML = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body>
<h1>Manga de teste</h1>
<div class="title-detail__list" id="rows"></div>
<nav class="npager" id="npager"></nav>
<script>
const TOTAL = 40;
const PER_PAGE = 20;
let current = 1;

function pageWindow(cur) {
    const nums = [];
    const push = (n) => { if (!nums.includes(n)) nums.push(n); };
    push(1);
    const start = cur <= 3 ? 2 : cur - 1;
    const end = cur >= 38 ? 39 : cur + 4;
    if (start > 2) nums.push('...');
    for (let n = start; n <= end; n++) push(n);
    if (end < 39) nums.push('...');
    push(TOTAL);
    return nums;
}

function renderPager() {
    document.getElementById('npager').innerHTML = pageWindow(current).map((n) => {
        if (n === '...') return '<span class="npager__ellipsis">...</span>';
        const cls = n === current ? 'npager__num is-active' : 'npager__num';
        return '<button class="' + cls + '" onclick="go(' + n + ')">' + n + '</button>';
    }).join('');
}

function renderRows() {
    const first = (current - 1) * PER_PAGE + 1;
    let html = '';
    for (let i = 0; i < PER_PAGE; i++) {
        const id = first + i;
        html += '<div class="title-detail__row">'
              + '<a class="title-detail__row-link" href="/chapter/' + id + '">'
              + '<span class="title-detail__row-num">Ch. ' + id + '</span>'
              + '</a></div>';
    }
    document.getElementById('rows').innerHTML = html;
}

function go(n) {
    current = n;
    renderPager();
    renderRows();
}

renderPager();
renderRows();
</script>
</body></html>
"""


def _pagina_ativa(page) -> int:
    texto = page.eval_on_selector(".npager__num.is-active", "el => el.innerText.trim()")
    return int(texto)


def test_npager_avanca_em_sequencia():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel="chromium")
        try:
            page = browser.new_page()
            page.set_content(FIXTURE_HTML)
            visitadas = [_pagina_ativa(page)]
            # PAGER_JS e o mesmo snippet de `_all_chapter_rows`: clica a proxima
            # pagina sequencial e retorna False quando nao ha proxima.
            for _ in range(TOTAL_PAGINAS * 2):
                if not page.evaluate(PAGER_JS):
                    break
                visitadas.append(_pagina_ativa(page))
        finally:
            browser.close()
    assert visitadas == list(range(1, TOTAL_PAGINAS + 1))

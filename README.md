# ScraperHub

Ferramenta pessoal de estudo (NAO comercial). Interface web local onde voce cola
um link e o scraper certo e detectado automaticamente.

## Como rodar

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
python -m uvicorn app.main:app --port 8765
```

Abra http://localhost:8765 no navegador.

Se `uv` estiver disponivel, o venv pode ser criado com `uv venv` e as
dependencias instaladas com `uv pip install -r requirements.txt`.
Depois do `pip install`, rode `python -m playwright install chromium` para
baixar o navegador usado pelo scraper de manga.

## Scrapers

- **MangaFire** (`mangafire`): sites com front no estilo mangafire.to,
  incluindo clones. O site e uma SPA renderizada por JS atras de Cloudflare,
  entao o scraper usa um Chromium headless (Playwright) em vez de HTTP puro.
  Aceita qualquer host que contenha "mangafire" e tambem URLs no formato
  `*/title/{slug}` ou `*/title/{slug}/chapter/{id}` quando nenhum outro scraper
  reconhece o host. A primeira carga de uma pagina demora ~10s (renderizacao).
- **Manga WordPress** (`wpmanga`): sites WordPress server-rendered cuja home
  lista capitulos como links `/manga/{slug}-chapter-N` (ex:
  w2.chainsmokercat.website). Tambem cobre o padrao Madara
  (`/manga/{slug}/chapter/{n}` e `/manga/{slug}/{capitulo}/`) e o
  ReadAllComics (`/comic/{slug}/{capitulo}/`). HTTP puro, rapido.
- **Galeria** (`gallery`): galerias de imagens via `gallery-dl` (biblioteca
  Python): imgur, pinterest, reddit, pixiv, boorus (danbooru/gelbooru/
  konachan/...), artstation, tapas, webtoons, x/twitter, bluesky. Trata a
  URL como galeria unica; sub-galerias encadeadas (`Queue`) sao ignoradas.
- **E-book** (`ebook`): baixa arquivos `.epub/.pdf/.mobi/.azw3/.fb2` diretos
  ou listados em uma pagina HTML. Conteudo com DRM (Adobe/Kindle) e
  recusado com erro amigavel (ver Avisos).
- **Arquivo/File host** (`filehost`): Google Drive (via `gdown`), MediaFire
  e links diretos `.zip/.rar/.7z/.iso/.tar/.gz/.mp4` com progresso por bytes.
  `mega.nz` ainda nao e suportado (erro amigavel).
- **Espelho de site** (`mirror`): espelha HTML e recursos do mesmo host.
  Nunca e detectado automaticamente; use o seletor "Espelho de site" na UI
  (modo forcado). Opcoes `depth` (padrao 2) e `max_pages` (padrao 15). O
  HTML nao e reescrito: os links permanecem absolutos.
- **Video** (`video`): fallback generico para qualquer URL http(s), usando
  `yt-dlp` (API Python embutida no executavel). O `ffmpeg` e baixado
  automaticamente ao lado do exe na primeira vez que salvar um video
  (build oficial BtbN win64 gpl); sem ele, baixa o melhor arquivo unico.

O seletor ao lado do campo de URL permite forcar um scraper especifico
(Auto / Espelho de site / E-book / Galeria); com "Auto" a deteccao e
automatica.

## Executavel (um arquivo so)

```powershell
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python -m PyInstaller --noconfirm --onefile --name ScraperHub --add-data "web;web" run.py
```

Gera `dist\ScraperHub.exe` (autossuficiente: FastAPI + Playwright + yt-dlp).
Dois cliques: sobe o servidor em 127.0.0.1:8765 e abre o navegador sozinho.
Na primeira execucao instala o Chromium do Playwright em `pw-browsers\`
ao lado do exe, se necessario. IMPORTANTE: ao rebuildar, apague `build\` e
`dist\` antes (um exe travado por processo em execucao impede a
sobrescrita e voce testa um build velho sem perceber).

## Avisos

- **DRM**: videos protegidos por DRM (Widevine/criptografia) nao sao
  suportados; o download falha com mensagem amigavel. O ScraperHub nao
  implementa burlar DRM sob nenhuma circunstancia. E-books com DRM
  (Adobe/Kindle: `.acsm/.azw/.azw3/.prc` ou magic bytes de Kindle) tambem
  sao recusados com erro amigavel.
- Downloads de manga sao salvos em `downloads/` (pasta ignorada pelo git).
- Uso pessoal/estudo apenas: respeite os termos de uso e os direitos autorais
  dos sites acessados.
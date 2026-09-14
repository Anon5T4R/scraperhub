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
  Downloads MangaFire rodam UM POR VEZ (lock) com pausa entre capitulos: o
  site bloqueia com CAPTCHA (Turnstile) sob acesso concorrente/rapido — o
  ScraperHub detecta o bloqueio, aborta com aviso claro e NAO burla CAPTCHA;
  capitulos ja baixados sao pulados ao tentar de novo. Quando o Cloudflare exige verificacao humana (challenge), o scraper nao burla o CAPTCHA: o painel do manga oferece o botao "Resolver verificacao", que abre uma janela do Chromium para VOCE resolver; os cookies resultantes (cf_clearance) sao salvos em mangafire-state.json (ignorado pelo git) e reaproveitados no info e nos downloads seguintes. O rotulo do capitulo
  inclui o idioma (`[English]` etc): o mesmo numero existe em varias linguas.
- **Manga WordPress** (`wpmanga`): sites WordPress server-rendered cuja home
  lista capitulos como links `/manga/{slug}-chapter-N` (ex:
  w2.chainsmokercat.website). Tambem cobre o padrao Madara
  (`/manga/{slug}/chapter/{n}` e `/manga/{slug}/{capitulo}/`) e o
  ReadAllComics (`/comic/{slug}/{capitulo}/`). HTTP puro, rapido.
- **Manga por pagina de serie** (`seriesmanga`): sites cuja PAGINA DA SERIE
  lista os capitulos (diferente do wpmanga, que le a home). Confirmado no
  asurascans.com: serie `/comics/{slug}`, capitulo `/comics/{slug}/chapter/{n}`,
  imagens de conteudo filtradas por `/chapters/` no CDN (capas/banners ficam
  fora). HTTP puro, com deteccao do slug canonico via redirect.
- **Tsundoku** (`tsundoku`): series PT-BR do tsundoku.com.br (light novels em
  texto e mangas com reader de imagens). A pagina da serie (`/manga/{slug}/`)
  lista todos os capitulos como links na raiz
  (`/{serie}-vol-N-cap-M-{titulo}/` ou `/{serie}-cap-NN-{titulo}/`); o numero
  do capitulo e o numero apos `cap-`. HTTP puro para listar; o download usa
  Playwright para renderizar o reader (`#readerarea`) e coletar as imagens
  (`img.ts-main-image`, com fallback para `data-src` das paginas lazy).
  Capitulos de novel (texto) nao tem paginas e sao pulados com aviso.
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
- **Anime (serie)** (`animestream`): series/temporadas em animeq.cloud (MP4
  direto), animesdigital.org (HLS via ffmpeg), otakubr.com (apenas listagem;
  o player Blogger do site e protegido e o download falha com aviso claro),
  animexnovel.com (episodios hospedados no Google Drive, baixados via gdown;
  alguns episodios podem estar restritos pelo dono do arquivo) e animefire.app
  (listagem completa por temporada `S1E01`; o player Blogger do site e
  protegido e o download falha com aviso claro, igual ao otakubr). Cole o link
  da pagina do anime: a UI lista todos os episodios com selecao multipla
  (por temporada no otakubr e animefire, `S1E01`).
- **Anime EN** (`enanime`): series em agregadores em ingles — animeheaven.me
  (MP4 direto do proprio CDN), gogoanime.is e 9anime.org.lv (episodios via
  servidor vidmoly, resolvido pelo yt-dlp como HLS). Cole o link da pagina
  da serie: a UI lista todos os episodios com selecao multipla (`Ep NN`).
  Quando o episodio so tem players protegidos (megaplay e afins), o download
  falha com aviso claro.
- **Video** (`video`): fallback generico para qualquer URL http(s), usando
  `yt-dlp` (API Python embutida no executavel). O `ffmpeg` e baixado
  automaticamente ao lado do exe na primeira vez que salvar um video
  (build oficial BtbN win64 gpl); sem ele, baixa o melhor arquivo unico.

O seletor ao lado do campo de URL permite forcar um scraper especifico
(Auto / Espelho de site / E-book / Galeria); com "Auto" a deteccao e
automatica.

## Troca de IP (fallback de bloqueio)

Quando um site bloqueia por taxa (rate-limit), o ScraperHub pode trocar o IP de
origem e tentar de novo. E opt-in e configuravel em `ip-switch.json` (na raiz
do app; ignorado pelo git) ou pelo painel "Troca de IP" na aba Manga.

- `provider: "off"` (padrao): desativado.
- `provider: "warp"`: reconecta o Cloudflare One/WARP via `warp-cli`
  (`disconnect` + `connect`) e confere o IP publico antes/depois.
- `provider: "custom"`: roda o `command` configurado (qualquer VPN/servico com
  CLI). `wait_seconds` define a espera apos a troca.
- `auto: true`: troca o IP sozinho ao detectar o bloqueio, em vez de apenas
  mostrar o painel assistido.

```json
{ "provider": "custom", "command": "wg-quick down wg0 && wg-quick up wg0", "wait_seconds": 8, "auto": false }
```

IMPORTANTE:
- A troca de IP NAO burla CAPTCHA — apenas muda a origem quando o site bloqueia
  por taxa. Quando a verificacao humana aparece, o usuario resolve no modo
  assistido.
- Cloudflare WARP e contraproducente contra challenge da Cloudflare: o WARP sai
  pela propria rede da Cloudflare, entao nao ajuda (e pode piorar) num site
  protegido pela Cloudflare; alem disso nao convive com outra VPN ativa.
- Proton VPN no Windows NAO tem CLI (o CLI oficial e so Linux): nao serve como
  provider; use `custom` se tiver um comando proprio.
- Kaspersky VPN nao tem CLI: troque o servidor pela interface e use o botao
  "Trocar de IP e tentar de novo".

## Executavel (um arquivo so, PORTATIL)

```powershell
# requer ffmpeg.exe na raiz do projeto (baixado automaticamente em algum
# download de video anterior, ou coloque manualmente) e o Chromium headless
# instalado pelo Playwright (%LOCALAPPDATA%\ms-playwright)
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --name ScraperHub `
  --add-data "web;web" `
  --add-binary "ffmpeg.exe;." `
  --add-data "$env:LOCALAPPDATA\ms-playwright\chromium_headless_shell-1234;ms-playwright/chromium_headless_shell-1234" `
  --add-data "$env:LOCALAPPDATA\ms-playwright\chromium-1234;ms-playwright/chromium-1234" `
  --collect-all gallery_dl --collect-all gdown run.py
```

Gera `dist\ScraperHub.exe` (~240MB) com TUDO embutido: FastAPI + Playwright
+ yt-dlp + gallery-dl + gdown + Chromium headless + ffmpeg. Zero downloads
ao abrir em outra maquina — so passe o exe. Dois cliques: sobe o servidor em
127.0.0.1:8765 e abre o navegador sozinho. A extracao interna do onefile faz
a abertura demorar ~15s a mais; e o preco do arquivo unico.

NOTAS:
- Ao rebuildar, apague `build\` e `dist\` antes (um exe travado por
  processo em execucao impede a sobrescrita e voce testa um build velho sem
  perceber).
- O numero da revisao do Chromium (ex: 1234) muda a cada versao do
  Playwright — confira o nome real da pasta em `%LOCALAPPDATA%\ms-playwright`
  e ajuste o comando.
- Sem rede nenhuma no build: o exe ainda baixa o Chromium/ffmpeg sozinho na
  primeira execucao, se faltarem no pacote (fallback do codigo).
- O modo assistido de CAPTCHA precisa do Chromium COMPLETO (chromium-XXXX) — por isso ele tambem vai no empacotamento. Isso aumenta o exe (~+150MB). Sem ele, so o modo headless funciona.

## Release

Fluxo manual (sem CI). A tag `vX.Y.Z` e a fonte da verdade da versao.

1. Bump da versao em `app/main.py` (`FastAPI(version="X.Y.Z")`) para a nova tag.
2. Commit das mudancas + do bump.
3. Tag: `git tag vX.Y.Z`.
4. Push: `git push origin master && git push origin vX.Y.Z`.
5. Release no GitHub (so a tag NAO marca "Latest"):
   `gh release create vX.Y.Z -R Anon5T4R/scraperhub --latest --title "ScraperHub vX.Y.Z" --notes "..."`.

## Avisos

- **DRM**: videos protegidos por DRM (Widevine/criptografia) nao sao
  suportados; o download falha com mensagem amigavel. O ScraperHub nao
  implementa burlar DRM sob nenhuma circunstancia. E-books com DRM
  (Adobe/Kindle: `.acsm/.azw/.azw3/.prc` ou magic bytes de Kindle) tambem
  sao recusados com erro amigavel.
- Downloads de manga sao salvos em `downloads/` (pasta ignorada pelo git).
- Uso pessoal/estudo apenas: respeite os termos de uso e os direitos autorais
  dos sites acessados.
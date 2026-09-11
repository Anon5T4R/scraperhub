"""Sonda: endpoints de busca dos sites de anime."""
import httpx
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
TERM = "yani"

with httpx.Client(headers=UA, follow_redirects=True, timeout=30) as client:
    print("== animeq (?s=) ==")
    r = client.get("https://animeq.cloud/", params={"s": TERM})
    soup = BeautifulSoup(r.text, "lxml")
    animes = [a.get("href") for a in soup.select('a[href*="/anime/"]')]
    uniq = [u for u in dict.fromkeys(animes) if u and u.rstrip("/").split("/")[-1]][:6]
    for u in uniq:
        print("  ", u)

    print("== animesdigital (tentativa ?s=) ==")
    for path, params in [("/", {"s": TERM}), ("/search", {"q": TERM}), ("/index", {"s": TERM})]:
        try:
            r = client.get(f"https://animesdigital.org{path}", params=params)
            soup = BeautifulSoup(r.text, "lxml")
            links = [a.get("href") for a in soup.select('a[href*="/anime/"]')]
            uniq = [u for u in dict.fromkeys(links) if u][:5]
            print(f"  {path}?{params} -> {r.status_code}, {len(uniq)} resultados")
            for u in uniq[:3]:
                print("    ", u)
        except Exception as exc:
            print(f"  {path}?{params} ERRO {exc}")
    # procura form de busca na home
    r = client.get("https://animesdigital.org/index")
    soup = BeautifulSoup(r.text, "lxml")
    form = soup.select_one("form[action*='search'], form[role=search]")
    if form:
        print("  FORM:", {k: v for k, v in form.attrs.items() if k in ("action", "method")}, "| inputs:", [i.get("name") for i in form.select("input")][:4])

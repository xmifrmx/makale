"""MediaWiki Action API istemcisi (en/tr.wikipedia.org/w/api.php).

- Tanımlayıcı User-Agent, maxlag, istekler arası bekleme (nazik kullanım)
- 429/5xx/ağ hatalarında üstel geri çekilme ve yeniden deneme
- 'continue' sayfalamasının birleştirilmesi
"""
from __future__ import annotations
import gzip
import http.client
import json
import random
import re
import time
import zlib
import urllib.error
import urllib.parse
import urllib.request

from . import config
from .textutil import EN_MONTHS, TR_MONTHS


class WikiError(RuntimeError):
    pass


def _default_transport(lang, params):
    url = f"https://{lang}.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": config.USER_AGENT, "Accept": "application/json", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def merge_query(dst, src):
    for key, val in src.items():
        if key == "pages":
            pages = dst.setdefault("pages", [])
            by = {p.get("title"): p for p in pages}
            for p in val:
                cur = by.get(p.get("title"))
                if cur is None:
                    pages.append(p)
                    by[p.get("title")] = p
                    continue
                for k, v in p.items():
                    if isinstance(v, list):
                        cur.setdefault(k, []).extend(v)
                    elif isinstance(v, dict):
                        cur.setdefault(k, {}).update(v)
                    else:
                        cur[k] = v
        elif isinstance(val, list):
            dst.setdefault(key, []).extend(val)
        elif isinstance(val, dict):
            dst.setdefault(key, {}).update(val)
        else:
            dst[key] = val


class Api:
    def __init__(self, transport=None, sleep=time.sleep, min_interval=0.2, retries=5):
        self.transport = transport or _default_transport
        self.sleep = sleep
        self.min_interval = min_interval
        self.retries = retries
        self._last = 0.0
        self.calls = 0

    def _throttle(self):
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            self.sleep(wait)
        self._last = time.monotonic()

    def _backoff(self, attempt, retry_after=None):
        try:
            delay = min(60.0, float(retry_after))
        except (TypeError, ValueError):
            delay = min(60.0, 2 ** attempt + random.random())
        self.sleep(delay)

    def request(self, lang, params):
        p = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
        last = None
        for attempt in range(self.retries):
            self._throttle()
            self.calls += 1
            try:
                data = self.transport(lang, p)
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (429, 500, 502, 503, 504):
                    self._backoff(attempt, e.headers.get("Retry-After") if e.headers else None)
                    continue
                raise WikiError(f"HTTP {e.code}") from e
            except (OSError, http.client.HTTPException, EOFError, zlib.error, ValueError) as e:
                # URLError/zaman aşımı/bağlantı kopması/yarım gövde/bozuk gzip/bozuk JSON: geçici sayılır
                last = e
                self._backoff(attempt)
                continue
            err = data.get("error") if isinstance(data, dict) else None
            if err:
                if err.get("code") in ("maxlag", "ratelimited"):
                    last = WikiError(err.get("code"))
                    self._backoff(attempt)
                    continue
                raise WikiError(f"{err.get('code')}: {err.get('info')}")
            return data
        raise WikiError(f"API yanıt vermedi ({lang}): {last}")

    def query(self, lang, **params):
        merged, cont = {}, {}
        for _ in range(40):
            data = self.request(lang, {"action": "query", **params, **cont})
            merge_query(merged, data.get("query", {}))
            if "continue" not in data:
                break
            cont = data["continue"]
        return merged


def page_index(q, keep_missing=False):
    """İstenen başlık (normalize/yönlendirme zinciri dahil) -> sayfa sözlüğü."""
    pages = {p.get("title"): p for p in q.get("pages", [])
             if keep_missing or not (p.get("missing") or p.get("invalid"))}
    alias = {}
    for key in ("normalized", "redirects"):
        for r in q.get(key, []):
            alias[r["from"]] = r["to"]

    def lookup(title):
        t, n = title, 0
        while t in alias and n < 6:
            t, n = alias[t], n + 1
        return pages.get(t)
    return lookup


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def date_page_title(lang, month, day):
    return f"{EN_MONTHS[month - 1]} {day}" if lang == "en" else f"{day} {TR_MONTHS[month - 1]}"


def get_wikitext(api, lang, title):
    q = api.query(lang, prop="revisions", rvprop="content", rvslots="main", titles=title, redirects=1)
    p = page_index(q)(title)
    if not p or not p.get("revisions"):
        return None
    return p["revisions"][0]["slots"]["main"]["content"]


def expand_templates(api, lang, text):
    """Şablon çağrısını (iç içe alt şablonlar dahil) viki metnine açar; biçimden bağımsız çalışır.
    Şablon yoksa Vikipedi '[[:Şablon:…]]' kırmızı bağlantı metni döndürür (çağıran bunu liste olarak görmez)."""
    data = api.request(lang, {"action": "expandtemplates", "text": text, "prop": "wikitext"})
    return ((data.get("expandtemplates") or {}).get("wikitext") or "") if isinstance(data, dict) else ""


def tr_titles_for(api, en_titles):
    """İngilizce başlık -> Türkçe Vikipedi başlığı (yalnızca karşılığı olanlar)."""
    out = {}
    for chunk in chunks(en_titles, 50):
        q = api.query("en", prop="langlinks", lllang="tr", lllimit="max",
                      titles="|".join(chunk), redirects=1)
        look = page_index(q)
        for t in chunk:
            p = look(t)
            if p and p.get("langlinks"):
                out[t] = p["langlinks"][0]["title"]
    return out


def intro_info(api, lang, titles):
    """Başlık -> {title, extract (giriş), thumbnail, pageimage, pageprops}."""
    out = {}
    for chunk in chunks(titles, 20):
        q = api.query(lang, prop="extracts|pageimages|pageprops", exintro=1, explaintext=1,
                      exlimit="max", piprop="thumbnail|name", pithumbsize=1280, pilimit="max",
                      ppprop="disambiguation", titles="|".join(chunk), redirects=1)
        look = page_index(q)
        for t in chunk:
            p = look(t)
            if p:
                out[t] = p
    return out


def full_page(api, lang, title):
    """Maddenin TAM düz metni + son revizyon numarası -> {'title','extract','rev'} ya da None (sayfa yok).

    Boş metin dönerse (API geçici olarak boş extract verebilir) bir kez daha denenir."""
    p, text = None, ""
    for _ in range(2):
        q = api.query(lang, prop="extracts|info", explaintext=1, exsectionformat="wiki",
                      titles=title, redirects=1)
        p = page_index(q)(title)
        if not p:
            return None
        text = p.get("extract") or ""
        if text.strip():
            break
    return {"title": p.get("title", title), "extract": text, "rev": p.get("lastrevid")}


def full_extract(api, lang, title):
    page = full_page(api, lang, title)
    return page["extract"] if page else ""


def revisions(api, lang, titles):
    """Başlık -> son revizyon numarası (içerik değişti mi kontrolü için; tek istekte 50 başlık)."""
    out = {}
    for chunk in chunks(list(dict.fromkeys(titles)), 50):
        q = api.query(lang, prop="info", titles="|".join(chunk), redirects=1)
        look = page_index(q)
        for t in chunk:
            p = look(t)
            if p and p.get("lastrevid"):
                out[t] = p["lastrevid"]
    return out


PERSON_CAT = re.compile(r"(doğumlular|ölenler|yaşayan insanlar|\bölümler\b|births|deaths|living people)", re.I)


def people_info(api, lang, titles):
    """Verilen sayfalardan kişi olanları (kategoriye göre) kısa tanımlarıyla döndürür."""
    out = []
    for chunk in chunks(titles, 20):
        q = api.query(lang, prop="categories|extracts", cllimit="max", exintro=1, explaintext=1,
                      exsentences=2, exlimit="max", titles="|".join(chunk), redirects=1)
        for p in q.get("pages", []):
            cats = [c.get("title", "") for c in p.get("categories", [])]
            if any(PERSON_CAT.search(c) for c in cats) and (p.get("extract") or "").strip():
                out.append({"title": p["title"], "intro": p["extract"].strip()})
    return out


def person_titles(api, lang, titles):
    """Verilen başlıklardan KİŞİ olanların kümesi (kategoriye göre: doğumlular/ölenler/yaşayan insanlar)."""
    out = set()
    for chunk in chunks(list(dict.fromkeys(titles)), 20):
        q = api.query(lang, prop="categories", cllimit="max", titles="|".join(chunk), redirects=1)
        look = page_index(q)
        for t in chunk:
            p = look(t)
            if p and any(PERSON_CAT.search(c.get("title", "")) for c in p.get("categories", [])):
                out.add(t)
    return out


def _strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def image_credit(api, lang, filename):
    """Görsel için sanatçı/lisans bilgisi (Commons extmetadata).

    Bilgi yoksa {} ; API geçici olarak yanıt vermediyse None (çağıran eksik işaretler, sonra tamamlanır)."""
    try:
        q = api.query(lang, prop="imageinfo", iiprop="extmetadata|url", titles="File:" + filename)
        p = page_index(q, keep_missing=True)("File:" + filename)
        ii = (p or {}).get("imageinfo", [{}])[0]
        ext = ii.get("extmetadata", {})
        g = lambda k: _strip_tags((ext.get(k) or {}).get("value", ""))
        return {"artist": g("Artist")[:120], "license": g("LicenseShortName"),
                "license_url": g("LicenseUrl"), "page": ii.get("descriptionurl", "")}
    except WikiError:
        return None
    except (KeyError, IndexError, TypeError):
        return {}

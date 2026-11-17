"""Gün sayfalarından (tr/en Vikipedi) aday toplama, değerlendirme ve çeşitlilik gözeten seçim."""
from __future__ import annotations
import hashlib
import random
import re

from . import config, wiki
from .textutil import EN_MONTHS, TR_MONTHS, norm_space, tr_lower

SECTION_KINDS = {"events": "olay", "olaylar": "olay", "births": "dogum", "doğumlar": "dogum",
                 "deaths": "olum", "ölümler": "olum"}

_YEAR_TOKEN = re.compile(r"^(?:(?:AD|MS|MÖ|M\.Ö\.|M\.S\.)\s*)?\d{1,4}(?:\s*(?:BC|AD|MÖ|MS))?$")
_YEAR_LINK = re.compile(r"^\[\[([^\]|]+)(?:\|([^\]]+))?\]\]\s*(?:[–—-]|&ndash;|&mdash;|:)?\s*(.*)$")
_YEAR_PLAIN = re.compile(r"^(\d{1,4}(?:\s?(?:BC|AD|MÖ|MS))?)\s*(?:[–—-]|&ndash;|&mdash;|:)\s*(.*)$")
_LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
_DATE_LIKE = re.compile(
    r"^(?:\d{1,4}(?:\s?(?:BC|AD|MÖ|MS))?|(?:%s) \d{1,2}|\d{1,2} (?:%s))$"
    % ("|".join(EN_MONTHS), "|".join(TR_MONTHS)))
_NS = re.compile(r"^(file|image|category|dosya|resim|kategori|vikipedi|wikipedia|şablon|template|help|yardım):", re.I)


def parse_year(token):
    token = token.strip()
    if not _YEAR_TOKEN.match(token):
        return None
    n = int(re.search(r"\d{1,4}", token).group())
    return -n if re.search(r"BC|MÖ|M\.Ö", token) else n


def strip_markup(text):
    """Vikimetinden (düz metin, [bağlantı başlıkları]) çıkarır."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<ref[^>]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    for _ in range(4):
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    links = []

    def repl(m):
        target = m.group(1).strip()
        disp = m.group(2)
        disp = target if disp is None or disp.strip() == "" else disp.strip()
        if _NS.match(target) or target.startswith(":"):
            return "" if re.match(r"^(file|image|category|dosya|resim|kategori)", target, re.I) else disp
        if not _DATE_LIKE.match(target) and target not in links:
            links.append(target)
        return disp
    text = _LINK.sub(repl, text)
    text = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\]", "", text)
    text = text.replace("'''", "").replace("''", "").replace("[[", "").replace("]]", "")
    return norm_space(text), links


def _split_year(body):
    m = _YEAR_LINK.match(body)
    if m:
        y = parse_year((m.group(2) or m.group(1)).strip()) or parse_year(m.group(1).strip())
        if y is not None:
            return y, m.group(3)
    m = _YEAR_PLAIN.match(body)
    if m:
        y = parse_year(m.group(1))
        if y is not None:
            return y, m.group(2)
    return None, body


def parse_day_wikitext(text, lang, month, day):
    cands, kind, pending = [], None, None
    for raw in text.splitlines():
        line = raw.rstrip()
        h = re.match(r"^(={2,6})\s*(.*?)\s*\1\s*$", line)
        if h:
            if len(h.group(1)) == 2:
                name = tr_lower(re.sub(r"[\[\]']", "", h.group(2)).strip())
                kind, pending = SECTION_KINDS.get(name), None
            continue
        m = re.match(r"^(\*+)\s*(.*)$", line)
        if not m or kind is None:
            continue
        depth, body = len(m.group(1)), m.group(2)
        year, rest = _split_year(body)
        if year is None and depth > 1 and pending is not None:
            year, rest = pending, body
        if year is None:
            continue
        if not rest.strip():
            pending = year
            continue
        plain, links = strip_markup(rest)
        if len(plain) < 12 or not links:
            continue
        cid = hashlib.sha1(f"{lang}|{kind}|{year}|{plain[:80]}".encode("utf-8")).hexdigest()[:16]
        cands.append({"id": cid, "lang": lang, "kind": kind, "year": year, "text": plain,
                      "links": links, "month": month, "day": day})
    return cands


def build_pool(api, month, day, log=print, failed=None):
    """tr + en gün sayfalarındaki TÜM olay/doğum/ölüm adayları. Alınamayan dil `failed` listesine eklenir."""
    pool = []
    for lang in ("tr", "en"):
        title = wiki.date_page_title(lang, month, day)
        try:
            text = wiki.get_wikitext(api, lang, title)
        except wiki.WikiError as e:
            log(f"::warning::{lang}.wikipedia '{title}' alınamadı: {e}")
            if failed is not None:
                failed.append(lang)
            continue
        if not text:
            log(f"::warning::{lang}.wikipedia '{title}' sayfası boş/bulunamadı")
            continue
        found = parse_day_wikitext(text, lang, month, day)
        log(f"{lang}: '{title}' -> {len(found)} aday")
        pool += found
    return pool


# ---------- sınıflandırma (çeşitlilik için) ----------
def era_bucket(y):
    for i, limit in enumerate((500, 1500, 1800, 1900, 1950)):
        if y < limit:
            return i
    return 5


TOPIC_RULES = [
    ("savaş", r"savaş|muharebe|kuşat|işgal|çatışma|ordu|saldır|zafer|sefer|fetih|asker"),
    ("bilim", r"bilim|keşf|icat|teori|uzay|uydu|fizik|kimya|tıp|teleskop|aşı|astronom|matemati|mühendis"),
    ("siyaset", r"bağımsızlık|cumhuriyet|devrim|antlaşma|anlaşma|seçim|kral|imparator|hükümet|anayasa|devlet|başkan|başbakan|siyasetçi|sultan|padişah|parlamento"),
    ("kültür", r"film|müzik|sanat|roman|opera|tiyatro|kitap|şiir|albüm|festival|ressam|yazar|şair|besteci|oyuncu|yönetmen|heykel|mimar"),
    ("doğa", r"deprem|fırtına|\bsel\b|yanardağ|kuraklık|felaket|kaza|salgın|hastalık|yangın"),
]
REGION_RULES = [
    ("Türkiye", r"türk|osmanlı|anadolu|istanbul|ankara"),
    ("Orta Doğu", r"iran|irak|suriye|arap|suudi|israil|filistin|lübnan|mısır|kudüs|bağdat"),
    ("Asya", r"çin|japon|hint|kore|moğol|vietnam|asya|tayland|endonezya|pakistan|afganistan|tibet"),
    ("Afrika", r"afrika|etiyopya|nijerya|cezayir|fas\b|tunus|sudan|kongo|kenya"),
    ("Amerika", r"abd|amerika|meksika|brezilya|kanada|arjantin|şili|küba|peru"),
    ("Rusya", r"rus|sovyet|ukrayna|moskova"),
    ("Avrupa", r"fransa|fransız|ingiltere|ingiliz|alman|italya|italyan|ispanya|polonya|letonya|avrupa|avusturya|hollanda|belçika|isveç|yunan|roma"),
]


def _tag(rules, text, default):
    low = tr_lower(text)
    for name, pat in rules:
        if re.search(pat, low):
            return name
    return default


def topic_of(text):
    return _tag(TOPIC_RULES, text, "genel")


def region_of(text):
    return _tag(REGION_RULES, text, "Diğer")


# ---------- aday değerlendirme ----------
EVENT_WORDS = re.compile(
    r"(savaş|muharebe|kuşatma|antlaşma|anlaşma|sözleşme|devrim|ihtilal|isyan|ayaklanma|darbe|deprem|"
    r"fırtına|felaket|kaza|saldırı|işgal|fetih|ilan|bağımsızlık|kongre|konferans|zirve|sefer|keşf|uçuş|"
    r"inişi|fırlatma|misyon|seçim|kuruluş|katliam|soykırım|krizi|buhran|barış|ateşkes|grev|olayı|harekât|"
    r"harekat|operasyon|baskın|patlama|yangın|açılış|kadife|bildirge|bildirisi|çıkarma|bombardıman)")
GEO_INTRO = re.compile(r"\b(ülke|ülkesi|devlet|devleti|şehir|şehri|kent|kenti|ilçe|başkent|kıta|ada|adası|eyalet|bölge)\w*")
BAD_IMG = re.compile(r"(flag|bayrak|coat[_ ]of|arms|logo|symbol|map\b|harita|signature|imza|locator|location)")


def image_from_page(p):
    th = p.get("thumbnail")
    if not th or not th.get("source"):
        return None
    name = p.get("pageimage", "") or ""
    low = name.lower()
    good = th.get("width", 0) >= 700 and not BAD_IMG.search(low) and not low.endswith(".svg")
    return {"url": th["source"], "width": th.get("width"), "height": th.get("height"),
            "name": name, "good": good}


def topic_key(title):
    return "tr:" + tr_lower(title.strip())


def event_like_title(title):
    return bool(EVENT_WORDS.search(tr_lower(title)))


def enrich(best, c):
    """Seçilen sayfa + aday -> çeşitlilik etiketleri (konu/bölge/dönem). Hem ilk üretimde hem yeniden derlemede kullanılır."""
    ctx = (c["text"] if c["lang"] == "tr" else "") + " " + best["title"] + " " + (best["info"].get("extract") or "")[:300]
    best.update({"cand": c, "topic": topic_of(ctx), "region": region_of(ctx), "era": era_bucket(c["year"]),
                 "image_ok": bool(best["image"] and best["image"]["good"])})
    return best


def evaluate_chunk(api, chunk, used_topics, log=print):
    """-> (uygun_liste, durumlar). durumlar: aday_id -> 'skip' (uygun değil) | 'dup' (konu zaten yayımlandı).

    Ağ/API hatasında WikiError fırlatır; çağıran grubu 'error' işaretleyip sonra yeniden dener."""
    def src_links(c):
        return c["links"][:4] if c["kind"] == "olay" else c["links"][:1]

    en_needed = [t for c in chunk if c["lang"] == "en" for t in src_links(c)]
    mapping = wiki.tr_titles_for(api, list(dict.fromkeys(en_needed))) if en_needed else {}
    titles_for, all_titles = {}, []
    for c in chunk:
        ts = src_links(c) if c["lang"] == "tr" else [mapping[t] for t in src_links(c) if t in mapping]
        titles_for[c["id"]] = list(dict.fromkeys(ts))
        all_titles += ts
    uniq = list(dict.fromkeys(all_titles))
    infos = wiki.intro_info(api, "tr", uniq) if uniq else {}

    out, status = [], {}
    for c in chunk:
        best = None
        for idx, t in enumerate(titles_for[c["id"]]):
            p = infos.get(t)
            if not p or "disambiguation" in (p.get("pageprops") or {}):
                continue
            extract = (p.get("extract") or "").strip()
            if len(extract) < config.MIN_INTRO_CHARS:
                continue
            img = image_from_page(p)
            event_like = event_like_title(p["title"])
            score = max(0, 3 - idx) + (1 if img and img["good"] else 0) + min(2, len(extract) // 800)
            if c["kind"] == "olay":
                score += 4 if event_like else 0
                score += 2 if re.search(r"\d{3,4}", p["title"]) else 0
                if GEO_INTRO.search(tr_lower(extract[:220])) and not event_like:
                    score -= 4
            if best is None or score > best["score"]:
                best = {"title": p["title"], "info": p, "image": img, "event_like": event_like, "score": score}
        if not best:
            status[c["id"]] = "skip"
            continue
        if c["lang"] == "en" and c["kind"] == "olay" and not best["event_like"]:
            status[c["id"]] = "skip"      # İngilizce olay cümlesini çeviremeyiz; yalnızca olay sayfası net ise kullan
            continue
        if topic_key(best["title"]) in used_topics:
            status[c["id"]] = "dup"       # bu konu daha önce yayımlandı: asla tekrar eklenmez
            continue
        out.append(enrich(best, c))
    return out, status


# ---------- sıralama ve seçim ----------
def _interleave(lists):
    lists = [list(l) for l in lists if l]
    out = []
    while lists:
        for l in list(lists):
            out.append(l.pop(0))
            if not l:
                lists.remove(l)
    return out


def _weave(a, b, ra=1, rb=1):
    a, b, out = list(a), list(b), []
    while a or b:
        out += [a.pop(0) for _ in range(min(ra, len(a)))]
        out += [b.pop(0) for _ in range(min(rb, len(b)))]
    return out


def diversify(pool, seed):
    """Tüm adayları dönem/tür/dil çeşitliliği gözeten kararlı bir sıraya dizer (hiçbirini atmaz)."""
    rng = random.Random(seed)

    def by_era(items):
        groups = {}
        for it in items:
            groups.setdefault(era_bucket(it["year"]), []).append(it)
        keys = sorted(groups)
        rng.shuffle(keys)
        lists = []
        for k in keys:
            rng.shuffle(groups[k])
            lists.append(groups[k])
        return _interleave(lists)

    sel = lambda lang, kind: by_era([c for c in pool if c["lang"] == lang and c["kind"] == kind])
    events = _weave(sel("tr", "olay"), sel("en", "olay"), 2, 1)
    people = _interleave([_weave(sel("tr", "dogum"), sel("en", "dogum"), 1, 1),
                          _weave(sel("tr", "olum"), sel("en", "olum"), 1, 1)])
    return _weave(events, people, 1, 1)


def needs_work(entry):
    """Günlük aday durumu (data/index.json -> days) yeniden işlenmeli mi?

    kayıt yok -> evet | 'error' (API hatası) -> sınırlı yeniden dene | 'skip' -> bir kez daha dene
    (sabah-14:47 arası Vikipedi'de sayfa eklenmiş olabilir) | 'published'/'dup' -> hayır."""
    if not entry:
        return True
    st, n = entry.get("s"), entry.get("n", 1)
    if st == "error":
        return n < config.MAX_ERROR_ATTEMPTS
    if st == "skip":
        return n < config.MAX_SKIP_ATTEMPTS
    return False


def select_candidates(api, pool, used_topics, state, published, day, log=print, limit=0):
    """Güne ait TÜM işlenmemiş adayları değerlendirir (sayı sınırı yok).

    -> (uygun_liste_sirali, durumlar, hatalar)
    published: bu güne ait yayımlanmış olay kimlikleri; state: günlük aday durumları."""
    order = [c for c in diversify(pool, day.isoformat())
             if c["id"] not in published and needs_work(state.get(c["id"]))]
    viable, seen, status, errors, evaluated, streak = [], set(), {}, [], 0, 0
    for chunk in wiki.chunks(order, 8):
        if limit > 0 and evaluated >= limit:
            break
        evaluated += len(chunk)
        try:
            found, st = evaluate_chunk(api, chunk, used_topics, log)
            streak = 0
        except wiki.WikiError as e:
            log(f"::warning::aday değerlendirmesi başarısız ({e}); bu grup sonraki çalışmada yeniden denenecek")
            errors.append(str(e))
            for c in chunk:
                status[c["id"]] = "error"
            streak += 1
            if streak >= 3:        # API kesintisi: kalan adayları işaretlemeden bırak, sonraki çalışma sürdürsün
                log("::warning::ardışık API hatası: değerlendirme durduruldu")
                break
            continue
        status.update(st)
        for ev in found:
            if ev["title"] in seen:
                status[ev["cand"]["id"]] = "dup"    # aynı konuya giden kardeş aday zaten sırada; sonuç konuya bağlıdır
                continue
            seen.add(ev["title"])
            viable.append(ev)
    log(f"{evaluated} aday değerlendirildi, {len(viable)} uygun")
    return viable, status, errors

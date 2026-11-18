"""Seçilen adaydan Blogger uyumlu (H1'siz) tam makale HTML'i üretir.

Makale yalnızca Vikipedi'den alınan bilgilere dayanır; uydurma bilgi eklenmez.
Veri yetersizse ilgili bölüm atlanır (boş/dolgu bölüm üretilmez).
"""
from __future__ import annotations
import hashlib
import html
import re
import urllib.parse
from datetime import timezone

from . import config, wiki
from .sources import _LINK
from .textutil import (TR_MONTHS, century_label, clean_name, date_phrase, day_phrase, make_title, norm_space,
                       sentences, slugify, split_first_sentences, tr_lower, word_cut, year_label)

def esc(s, quote=False):
    return html.escape(s, quote=quote)

SKIP_SECTIONS = re.compile(
    r"^(kaynakça|kaynaklar|dış bağlantılar?|dış kaynaklar?|ayrıca bak(ınız)?|notlar|dipnotlar?|referanslar?|"
    r"bibliyografya|galeri|ilgili yayınlar|konuyla ilgili (yayınlar|okumalar)|önemli kaynaklar|bağlantılar)\b", re.I)
BG_KEYS = re.compile(r"tarihçe|tarihi|arka plan|köken|öncesi|geçmiş|nedenleri|erken|çocukluk|gençlik|ilk yıl|hayatı|yaşamı|kuruluş", re.I)
IMPACT_KEYS = re.compile(r"etki|sonuç|miras|sonras|değerlendirme|önemi|eleştiri|anma|anısı|ödül|günümüz|kültürel|popüler|bugün", re.I)


def wiki_url(lang, title):
    return f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="()_,:'")


def page_link(slug):
    return f"{config.SITE_URL}/makale/{slug}.html"


_MATH = re.compile(r"\{\\displaystyle(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}")


def _keep_line(s):
    """Boş/süs satırlar dışında HER satır korunur (kısa liste maddeleri dahil; metin kaybı olmaz)."""
    if len(s) < 3 or re.search(r"\w", s) is None:
        return False
    rest = _MATH.sub("", s)                         # yalnızca matematik gösterimi olan satırlar (okunamaz) atılır
    return rest == s or re.search(r"[^\W\d_]{2,}", rest) is not None


def _prune(sections):
    """Atlanacak bölümleri çıkarır; kendi metni olmayan ama altında metinli alt bölümü olan başlığı korur."""
    keep = []
    for i, sec in enumerate(sections):
        if sec["skip"]:
            continue
        if sec["paras"]:
            keep.append(sec)
            continue
        for nxt in sections[i + 1:]:
            if nxt["level"] <= sec["level"]:
                break
            if not nxt["skip"] and nxt["paras"]:
                keep.append(sec)
                break
    return keep


def split_sections(text):
    lead, sections, cur, skip_at = [], [], None, None
    for line in (text or "").splitlines():
        s = line.strip()
        m = re.match(r"^(={2,6})\s*(.+?)\s*\1$", s)
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            if skip_at is not None and level <= skip_at:
                skip_at = None
            if skip_at is None and SKIP_SECTIONS.search(title):
                skip_at = level                       # bu başlık ve tüm alt başlıkları atlanır
            cur = {"title": title, "level": level, "paras": [], "skip": skip_at is not None}
            sections.append(cur)
            continue
        if _keep_line(s):
            (cur["paras"] if cur else lead).append(norm_space(s))
    return lead, _prune(sections)


class Budget:
    """limit <= 0 ise sınırsız: maddenin tüm paragrafları alınır."""

    def __init__(self, limit):
        self.left = limit if limit > 0 else None

    def take(self, paras, n=None):
        out = []
        for p in (paras if n is None else paras[:n]):
            if self.left is not None:
                if self.left <= 0:
                    break
                p = p if len(p) <= self.left else word_cut(p, max(self.left, 200), ellipsis=True)
                self.left -= len(p)
            out.append(p)
        return out


_SENT_END = (".", "!", "?", "…", ":", '"', "”", "»")


def _is_item(p):
    return len(p) <= 140 and not p.endswith(_SENT_END)


def paras_html(paras):
    """Paragraflar <p> olur; cümle noktalaması olmayan, art arda 3+ kısa satır liste (<ul>) olarak yazılır."""
    out, i = [], 0
    while i < len(paras):
        j = i
        while j < len(paras) and _is_item(paras[j]):
            j += 1
        if j - i >= 3:
            out.append("<ul>\n" + "".join(f"<li>{esc(p)}</li>\n" for p in paras[i:j]) + "</ul>\n")
            i = j
        else:
            out.append(f"<p>{esc(paras[i])}</p>\n")
            i += 1
    return "".join(out)


_HEAD = {2: "h3", 3: "h4"}


def blocks_html(blocks):
    """blocks: [(başlık, seviye, paragraflar)]. Vikipedi başlık hiyerarşisi h3/h4/h5 olarak korunur."""
    out = []
    for i, (t, lvl, ps) in enumerate(blocks):
        if not ps and not (i + 1 < len(blocks) and blocks[i + 1][1] > lvl):
            continue                                   # altı boş kalmış başlık yazılmaz
        tag = _HEAD.get(lvl, "h5")
        out.append(f"<{tag}>{esc(t)}</{tag}>\n{paras_html(ps)}")
    return "".join(out)


def _has_text(blocks):
    return any(ps for _, _, ps in blocks)


def unique_slug(rec, taken):
    """Aynı slug başka makalede varsa -2, -3… eklenir; makale/içerik dosyası asla ezilmez."""
    base = slug = rec["slug"]
    n = 1
    while slug in taken:
        n += 1
        slug = f"{base}-{n}"
    if slug != rec["slug"]:
        rec["slug"] = slug
        rec["content_file"] = f"data/content/{slug}.html"
        rec["link"] = page_link(slug)
    return rec


def _first_sentence(text, limit=220):
    s = sentences(norm_space(text))
    return word_cut(s[0], limit, ellipsis=True) if s else ""


def _related_titles(api, title, cand):
    titles = [t for t in cand["links"] if cand["lang"] == "tr"]
    wt = wiki.get_wikitext(api, "tr", title) or ""       # WikiError yukarı iletilir: 'kisiler' eksiği olarak işaretlenir
    for m in _LINK.finditer(wt[:7000]):
        t = m.group(1).strip()
        if ":" not in t and not re.fullmatch(r"\d{1,4}", t):
            titles.append(t)
    seen, out = {tr_lower(title)}, []
    for t in titles:
        if tr_lower(t) not in seen:
            seen.add(tr_lower(t))
            out.append(t)
    return out[:30]


KEEP_KEYS = ("id", "slug", "pub", "date", "content_file", "link", "topic_key", "event_id")


def build_article(api, ev, day, now_utc, log=print, keep=None):
    """-> (kayıt sözlüğü, içerik HTML) ya da yetersiz içerikte None.

    API geçici olarak yanıt vermezse WikiError fırlatır (çağıran adayı sonra yeniden dener). Makale yine de
    üretilebiliyor ama bir parça eksik kalmışsa kayıttaki `gaps` listesine yazılır; 14:47 çalışması bunu
    TEK PARÇA olarak yeniden derleyip tamamlar. `keep` verilirse (yeniden derleme) id/guid, slug, yayın
    zamanı ve bağlantı aynen korunur."""
    c, title, info = ev["cand"], ev["title"], ev["info"]
    kind, year = c["kind"], c["year"]
    name = clean_name(title)
    gaps = []
    page = wiki.full_page(api, "tr", title)
    full, rev = (page["extract"], page["rev"]) if page else ("", None)
    if not full.strip():
        gaps.append("metin")
        full = info.get("extract", "")
    lead, sections = split_sections(full)
    if not lead:
        lead = [norm_space(p) for p in (info.get("extract") or "").splitlines() if _keep_line(p.strip())]
    if not lead:
        raise wiki.WikiError(f"metin alınamadı: {title}")
    total = sum(len(p) for p in lead) + sum(len(p) for s in sections for p in s["paras"])
    if total < config.MIN_TOTAL_CHARS:
        if "metin" in gaps:
            raise wiki.WikiError(f"tam metin alınamadı: {title}")      # kısa görünmesi API aksaklığından olabilir
        log(f"  atlandı (metin kısa: {total}): {title}")
        return None

    when = date_phrase(c["day"], c["month"], year) if year is not None else day_phrase(c["day"], c["month"])
    event_sentence = c["text"].rstrip(" .") + "." if (kind in ("olay", "ozel_gun") and c["lang"] == "tr") else ""
    page_title = make_title(kind, year, title, c["text"] if event_sentence else "", ev["event_like"])

    # --- kısa özet ---
    if kind == "dogum":
        s1 = f"{name}, {when} tarihinde dünyaya geldi."
    elif kind == "olum":
        s1 = f"{name}, {when} tarihinde hayatını kaybetti."
    elif event_sentence:
        s1 = f"Tarihte bugün, {when}: {event_sentence}"
    else:    # İngilizce gün sayfasından gelen olay/özel gün: cümle çevrilmez, uydurma bilgi eklenmez
        s1 = f"Tarihte bugün, {when}: {name} maddesiyle ilişkilendirilen bir gelişme veya özel gün."
    summary_text, lead_rest = split_first_sentences(lead[0], 380)
    summary = (f"<p>{esc(s1)}</p>\n" if s1 else "") + f"<p>{esc(summary_text)}</p>\n"

    # --- bölümlerin dağıtımı ---
    budget = Budget(config.MAX_BODY_CHARS)
    bg_blocks, dev_blocks, impact_blocks = [], [], []
    # girişin TAMAMI: ilk paragrafın özete sığmayan cümleleri + sonraki tüm giriş paragrafları
    bg_paras = budget.take(([lead_rest] if lead_rest else []) + lead[1:])
    parent_bucket = dev_blocks
    for s in sections:
        if s["level"] <= 2:
            parent_bucket = (impact_blocks if IMPACT_KEYS.search(s["title"])
                             else bg_blocks if BG_KEYS.search(s["title"]) else dev_blocks)
        parent_bucket.append((s["title"], s["level"], budget.take(s["paras"])))
    dev_intro = []

    # --- önemli kişiler ---
    people_items = []
    try:
        related = wiki.people_info(api, "tr", _related_titles(api, title, c))
    except wiki.WikiError:
        related = []
        gaps.append("kisiler")
    if kind in ("dogum", "olum"):
        people_items.append((title, _first_sentence(info.get("extract", ""))))
    for p in related[:5 if kind in ("olay", "ozel_gun") else 4]:
        people_items.append((p["title"], _first_sentence(p["intro"])))

    # --- görsel ---
    img = ev["image"]
    cover_credit = {}
    if img:
        cover_credit = wiki.image_credit(api, "tr", img["name"]) if img.get("name") else {}
        if cover_credit is None:                       # API yanıt vermedi: görsel bilgisi sonra tamamlanır
            cover_credit = {}
            gaps.append("gorsel_bilgisi")
        src, w, h = img["url"], img.get("width") or 1280, img.get("height") or 720
    else:
        src, w, h = f"{config.SITE_URL}/{config.DEFAULT_COVER}", 1280, 720
    alt = (f"{name} ile ilgili tarihî görsel ({year_label(year)})" if kind == "olay" and year is not None
           else f"{name} ile ilgili görsel")
    if img:
        bits = ["Görsel: Vikipedi / Wikimedia Commons"]
        if cover_credit.get("artist"):
            bits.append(cover_credit["artist"])
        if cover_credit.get("license"):
            bits.append(cover_credit["license"])
        cap_inner = esc(" – ".join(bits))
        if cover_credit.get("page"):
            cap_inner = f'<a href="{esc(cover_credit["page"], True)}" rel="noopener">{cap_inner}</a>'
    else:
        cap_inner = "Konuyla ilgili özgün görsel bulunamadı; varsayılan kapak kullanıldı."
    cover = (f'<div class="separator" style="clear: both; text-align: center;">'
             f'<img alt="{esc(alt, quote=True)}" border="0" height="{h}" src="{esc(src, quote=True)}" '
             f'style="max-width: 100%; height: auto;" width="{w}" /></div>\n'
             f'<p style="text-align: center; font-size: 85%;"><em>{cap_inner}</em></p>\n')

    # --- gövde ---
    is_event = kind in ("olay", "ozel_gun")
    h2_dev = ("Olayın Gelişimi" if kind == "olay" else "Tarihi ve Gelişimi") if is_event else "Hayatı ve Öne Çıkan Gelişmeler"
    h2_people = "Önemli Kişiler" if is_event else "Önemli Kişiler ve Çevresi"
    parts = [cover, "<h2>Kısa Özet</h2>\n", summary]
    if bg_paras or _has_text(bg_blocks):
        parts += ["<h2>Tarihî Arka Plan</h2>\n", paras_html(bg_paras), blocks_html(bg_blocks)]
    if dev_intro or _has_text(dev_blocks):
        parts += [f"<h2>{h2_dev}</h2>\n", paras_html(dev_intro), blocks_html(dev_blocks)]
    if people_items:
        lis = "".join(f"<li><strong>{esc(t)}</strong>{' – ' + esc(d) if d else ''}</li>\n" for t, d in people_items)
        parts += [f"<h2>{h2_people}</h2>\n<ul>\n{lis}</ul>\n"]
    if _has_text(impact_blocks):
        parts += ["<h2>Dünya Tarihindeki Etkileri</h2>\n", blocks_html(impact_blocks)]

    variant = int(hashlib.sha1(title.encode("utf-8")).hexdigest(), 16) % 3
    topic_txt = esc(name)
    conclusions = {
        "olay": [f"{topic_txt}, {esc(when)} tarihiyle anılan ve Vikipedi kaynaklarında ayrıntılı biçimde ele alınan bir tarihî başlıktır. Yukarıdaki özet genel çerçeveyi sunar; kesin ve doğrulanmış ayrıntılar için aşağıdaki kaynaklara başvurulması önerilir.",
                 f"Tarihte bugün hatırlanan bu gelişme, {esc(when)} tarihinden itibaren dönemin siyasi ve toplumsal hafızasında yer edinmiştir. Konuyu daha derinlemesine incelemek isteyenler için ilgili kaynaklar aşağıda listelenmiştir.",
                 f"{topic_txt} konusu, tarihî olayların bugünle bağını anlamak açısından incelemeye değerdir. Bu yazı Vikipedi içeriğine dayanır; tarih, isim ve rakamları birincil kaynaklarla karşılaştırmak iyi bir uygulamadır."],
        "kisi": [f"{topic_txt}, tarih yazımında ve kültürel hafızada adı anılan isimlerden biridir. Yukarıdaki bilgiler Vikipedi'ye dayanır; ayrıntılar ve doğrulama için kaynak bağlantılarına göz atılabilir.",
                 f"{when} tarihiyle ilişkilendirilen {topic_txt}, yaşamı ve çalışmalarıyla incelenmeye değer bir isimdir. Kesin bilgiler için aşağıdaki kaynaklar esas alınmalıdır.",
                 f"{topic_txt} hakkındaki bu derleme, konuya giriş niteliğindedir. Daha geniş bir değerlendirme için ilgili Vikipedi maddesi ve kaynakçası incelenebilir."],
    }["olay" if is_event else "kisi"]
    parts += ["<h2>Sonuç</h2>\n", f"<p>{conclusions[variant]}</p>\n"]

    src_items = [f'<li><a href="{esc(wiki_url("tr", title), True)}" rel="noopener">{esc(title)} – Vikipedi</a></li>']
    for lang, label in (("tr", "Türkçe"), ("en", "İngilizce")):
        dt = wiki.date_page_title(lang, c["month"], c["day"])
        src_items.append(f'<li><a href="{esc(wiki_url(lang, dt), True)}" rel="noopener">{esc(dt)} – {label} Vikipedi gün sayfası</a></li>')
    if cover_credit.get("page"):
        src_items.append(f'<li><a href="{esc(cover_credit["page"], True)}" rel="noopener">Kapak görseli – Wikimedia Commons</a></li>')
    parts += ["<h2>Kaynaklar</h2>\n<ul>\n" + "\n".join(src_items) + "\n</ul>\n",
              '<p><small>Metin, Vikipedi içeriğinden derlenmiştir ve <a href="https://creativecommons.org/licenses/by-sa/4.0/deed.tr" '
              'rel="noopener">CC BY-SA 4.0</a> lisansı kapsamındadır. Tarih bilgileri Vikipedi gün sayfalarından alınmıştır.</small></p>\n']
    body = "".join(parts)
    assert "<h1" not in body.lower()

    # --- meta açıklama (<=155, mümkünse cümle sınırında) ---
    sent1 = (sentences(summary_text) or [summary_text])[0]
    options = [f"{s1} {sent1}".strip(), s1, sent1]
    meta = next((norm_space(o) for o in options if o and len(norm_space(o)) <= 155), None) \
        or word_cut(norm_space(options[0] or options[2]), 155, ellipsis=True)

    day_iso = day.isoformat()
    slug = f"{day_iso}-{slugify(c['text'] if (kind == 'olay' and event_sentence) else name, 48)}"
    guid_src = f"{c['id']}|{title}"
    rec = {
        "id": "tarih-" + hashlib.sha1(guid_src.encode("utf-8")).hexdigest()[:20],
        "slug": slug, "title": page_title, "description": meta, "v": config.BUILD_VERSION,
        "rev": rev, "gaps": gaps, "complete": not gaps, "chars": total, "src": {"cand": c},
        "pub": now_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date": day_iso, "kind": kind, "year": year, "topic_title": title,
        "topic_key": "tr:" + tr_lower(title.strip()), "event_id": c["id"], "wiki_url": wiki_url("tr", title),
        "image": {"url": src, "width": w, "height": h, "alt": alt, "fallback": not bool(img)},
        "categories": [c for c in [{"olay": "Olay", "dogum": "Doğum", "olum": "Ölüm", "ozel_gun": "Özel Gün"}[kind], name,
                                    century_label(year) if year is not None else "", "Tarihte Bugün",
                                    ev["topic"].capitalize()] if c],
        "content_file": f"data/content/{slug}.html",
        "link": page_link(slug),
    }
    if keep:
        for k in KEEP_KEYS:
            if k in keep:
                rec[k] = keep[k]
    return rec, body

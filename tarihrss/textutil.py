"""Metin yardımcıları: Türkçe büyük/küçük harf, slug, cümle bölme, 70 karakterlik başlık üretimi."""
from __future__ import annotations
import re
import unicodedata

TITLE_MAX = 70
TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
             "Eylül", "Ekim", "Kasım", "Aralık"]
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]

_ASCII = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
                        "Ç": "c", "Ğ": "g", "İ": "i", "I": "i", "Ö": "o", "Ş": "s", "Ü": "u"})
_XML_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def tr_lower(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def tr_upper_first(s: str) -> str:
    if not s:
        return s
    return {"i": "İ", "ı": "I"}.get(s[0], s[0].upper()) + s[1:]


def xml_clean(s: str) -> str:
    return _XML_BAD.sub("", s)


def slugify(text: str, max_len: int = 60) -> str:
    t = text.translate(_ASCII)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    if len(t) > max_len:
        t = t[:max_len].rsplit("-", 1)[0] or t[:max_len]
    return t or "makale"


def year_label(y: int) -> str:
    return f"M.Ö. {abs(y)}" if y < 0 else str(y)


def date_phrase(day: int, month: int, year: int) -> str:
    return f"{day} {TR_MONTHS[month - 1]} {year_label(year)}"


def century_label(y: int) -> str:
    c = (abs(y) - 1) // 100 + 1
    return f"M.Ö. {c}. yüzyıl" if y < 0 else f"{c}. yüzyıl"


def clean_name(t: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", t).strip()


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\u00a0", " ")).strip()


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ0-9\"“‘'(])")


_ABBR = {"d", "ö", "yy", "bk", "vb", "vs", "örn", "yak", "mö", "ms", "dr", "prof", "st", "no", "bkz", "c", "y"}


def sentences(text: str) -> list[str]:
    """Cümlelere böler; 'd. 1860', 'M.Ö.', 'W. S.' gibi kısaltmalarda bölmez."""
    out: list[str] = []
    for piece in _SENT.split(text.strip()):
        piece = piece.strip()
        if not piece:
            continue
        if out:
            last = out[-1].split()[-1].rstrip(".")
            if len(last) <= 2 or "." in last or tr_lower(last.replace(".", "")) in _ABBR:
                out[-1] += " " + piece
                continue
        out.append(piece)
    return out


def word_cut(text: str, limit: int, ellipsis: bool = False) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    room = limit - 1 if ellipsis else limit
    cut = text[:room].rsplit(" ", 1)[0].rstrip(" ,;:-–")
    return cut + ("…" if ellipsis else "")


def first_sentences(text: str, max_chars: int) -> str:
    out = ""
    for s in sentences(text):
        if out and len(out) + 1 + len(s) > max_chars:
            break
        out = f"{out} {s}".strip()
        if len(out) >= max_chars * 0.6:
            break
    return out if len(out) <= max_chars else word_cut(out, max_chars, ellipsis=True)


def split_first_sentences(text: str, max_chars: int) -> tuple[str, str]:
    """-> (özet, kalan). Özet cümle sınırında biter; kalan metin hiçbir şey kaybetmeden döner.

    Tek cümle bile sınırı aşıyorsa özet kelime sınırında kısaltılır ve kalan olarak
    paragrafın tamamı döner (içerik kaybı olmaz)."""
    sents = sentences(text)
    out, used = "", 0
    for s in sents:
        if out and len(out) + 1 + len(s) > max_chars:
            break
        out = f"{out} {s}".strip()
        used += 1
        if len(out) >= max_chars * 0.6:
            break
    if len(out) > max_chars:
        return word_cut(out, max_chars, ellipsis=True), text.strip()
    return out, " ".join(sents[used:])


_TRAIL = {"ve", "ile", "için", "bir", "bu", "de", "da", "ki", "olarak", "gibi", "kadar", "en", "çok"}


def smart_cut(s: str, limit: int) -> str:
    """Cümleyi mümkünse virgül/bağlaç sınırında keser; asla limiti aşmaz."""
    s = s.strip()
    if len(s) <= limit:
        return s
    head = s[:limit]
    cut = max(head.rfind(sep) for sep in (", ", " ve ", " ile ", " için "))
    if cut < 20:
        cut = head.rfind(" ")
    if cut <= 0:
        cut = limit
    words = head[:cut].rstrip(" ,;:-–").split(" ")
    while len(words) > 1 and tr_lower(words[-1]) in _TRAIL:
        words.pop()
    return " ".join(words)


def _fit(options: list[str], limit: int = TITLE_MAX) -> str | None:
    return next((o for o in options if len(o) <= limit), None)


def make_title(kind: str, year: int, topic: str, sentence: str = "", event_like: bool = False) -> str:
    """Konuya özel, doğal ve en fazla 70 karakterlik başlık. Garanti: len(sonuç) <= 70."""
    y = year_label(year)
    name = clean_name(topic) or topic
    if kind == "dogum":
        opts = [f"{name} Kimdir? Hayatı, Eserleri ve Tarihteki Yeri", f"{name} Kimdir? Hayatı ve Tarihteki Yeri",
                f"{name} Kimdir? Hayatı ve Önemi", f"{name} Kimdir?", name]
    elif kind == "olum":
        opts = [f"{name}: Hayatı, Mirası ve Tarihteki Etkisi ({y})", f"{name}: Hayatı ve Mirası ({y})",
                f"{name}: Hayatı ve Mirası", name]
    else:
        s = tr_upper_first(norm_space(sentence).rstrip(" .")) if sentence else ""
        opts = []
        if s:
            if len(s) <= 40:
                opts.append(f"{s} ({y}) – Tarihte Bugün")
            opts.append(f"{s} ({y})")
        if event_like or not s:
            opts += [f"{name} ({y}): Gelişmeler ve Tarihî Önemi", f"{name} ({y}): Tarihî Önemi", f"{name} ({y})"]
        t = _fit(opts)
        if t:
            return t
        base = s or name
        return f"{smart_cut(base, TITLE_MAX - len(f' ({y})'))} ({y})"
    return _fit(opts) or smart_cut(name, TITLE_MAX)

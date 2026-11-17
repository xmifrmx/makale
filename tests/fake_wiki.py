"""Ağsız test için sahte MediaWiki Action API. Gerçek yanıt biçimlerini (formatversion=2) taklit eder."""
import re

TR_DAY = """'''18 Kasım''' yılın 322. günüdür.
== Olaylar ==
=== 1500 sonrası ===
* [[1916]] - [[Somme Muharebesi]] sona erdi.
* [[1918]] - [[Letonya]], [[Rusya İmparatorluğu|Rusya]]'dan bağımsızlığını ilan etti.<ref>kaynak</ref>
* [[1989]] - [[Kadife Devrim]] kapsamında Prag'da büyük gösteriler başladı.
* [[MÖ 44]] - [[Bilinmeyen Sayfa]] hakkında bir olay yaşandı.
== Doğumlar ==
* [[1860]] - [[Ada Demir]], Türk şair
== Ölümler ==
* [[1923]] - [[Mehmet Kaya]], Türk devlet adamı
== Tatiller ==
* [[Letonya]] bağımsızlık günü
"""
EN_DAY = """'''November 18''' is the 322nd day.
==Events==
===Pre-1600===
* [[1477]] – [[William Caxton]] prints the first dated book in England.
===1900–present===
* [[1916]] – The [[Battle of the Somme]] ends.
==Births==
* [[1836]] – [[W. S. Gilbert]], English dramatist (d. 1911)
==Deaths==
* [[1980]] – [[Alexander Orlov]], Soviet spy (b. 1895)
==Holidays and observances==
* Something
"""
EN_TR = {"Battle of the Somme": "Somme Muharebesi", "W. S. Gilbert": "W. S. Gilbert",
         "Alexander Orlov": "Aleksandr Orlov", "William Caxton": "William Caxton"}

SENT = [
    "{t}, tarih boyunca farklı toplumların siyasi ve kültürel gelişimini etkileyen önemli bir başlık olarak değerlendirilir.",
    "Konuyla ilgili pek çok araştırma yapılmış, dönemin tanıklıkları ve belgeleri ayrıntılı biçimde incelenmiştir.",
    "Gelişmeler çevre ülkelerde de yankı bulmuş; çağdaş yazarlar bu süreci farklı açılardan yorumlamıştır.",
    "Özellikle ç, ğ, ı, İ, ö, ş ve ü harflerini içeren Türkçe ifadeler sorunsuz biçimde korunmalıdır.",
]


def paras(t, n):
    return [" ".join(s.format(t=t) for s in SENT) for _ in range(n)]


def page(t, lead=3, image="Kapak_gorsel.jpg", cats=(), disamb=False, first=None,
         sections=(("Tarihçe", 2), ("Gelişmeler", 2), ("Etkileri", 2), ("Kaynakça", 1))):
    lead_p = paras(t, lead)
    if first:
        lead_p[0] = first + " " + lead_p[0]
    return {"lead": lead_p, "sections": [(n, paras(t, k)) for n, k in sections],
            "image": image, "cats": list(cats), "disamb": disamb}


TR_PAGES = {
    "Letonya": page("Letonya", first="Letonya, Kuzey Avrupa'da bir ülkedir."),
    "Rusya İmparatorluğu": page("Rusya İmparatorluğu", first="Rusya İmparatorluğu, tarihte bir devlet idi."),
    "Somme Muharebesi": page("Somme Muharebesi", first="Somme Muharebesi, Birinci Dünya Savaşı sırasında yapılan büyük bir muharebedir."),
    "Kadife Devrim": page("Kadife Devrim", first="Kadife Devrim, 1989'da Çekoslovakya'da yaşanan barışçıl bir devrimdir."),
    "Ada Demir": page("Ada Demir", cats=["Kategori:1860 doğumlular"], first="Ada Demir (d. 1860), Türk şairdir."),
    "Mehmet Kaya": page("Mehmet Kaya", image=None, cats=["Kategori:1923 yılında ölenler"], first="Mehmet Kaya, Türk devlet adamıdır."),
    "W. S. Gilbert": page("W. S. Gilbert", cats=["Kategori:1836 doğumlular"], first="W. S. Gilbert, İngiliz oyun yazarıdır."),
    "Aleksandr Orlov": page("Aleksandr Orlov", image="Orlov_flag_logo.png", cats=["Kategori:1980 yılında ölenler"], first="Aleksandr Orlov, Sovyet ajanıdır."),
    "William Caxton": page("William Caxton", cats=["Kategori:1422 doğumlular"], first="William Caxton, matbaacıdır."),
    "Douglas Haig": page("Douglas Haig", cats=["Kategori:1861 doğumlular"], first="Douglas Haig, İngiliz mareşaldir."),
    "Václav Havel": page("Václav Havel", cats=["Kategori:1936 doğumlular"], first="Václav Havel, Çek yazar ve devlet adamıdır."),
}
PAGE_WT = {
    "Somme Muharebesi": "Giriş [[Douglas Haig]] komutasında ... [[Dosya:Foo.jpg]] [[1916]] [[Kategori:Muharebe]]",
    "Kadife Devrim": "[[Václav Havel]] liderliğinde ... [[Prag]]",
    "Letonya": "[[Riga]] başkenttir.",
}


def _intro(p):
    return "\n".join(p["lead"])


def _full(p):
    out = list(p["lead"])
    for n, ps in p["sections"]:
        out.append(f"== {n} ==")
        out += ps
    return "\n".join(out)


def transport(lang, p):
    prop = p.get("prop", "")
    titles = p["titles"].split("|") if p.get("titles") else []
    pages = []
    if prop == "revisions":
        t = titles[0]
        text = {("tr", "18 Kasım"): TR_DAY, ("en", "November 18"): EN_DAY}.get((lang, t)) or PAGE_WT.get(t)
        if text is None:
            return {"query": {"pages": [{"title": t, "missing": True}]}}
        pages = [{"pageid": 1, "title": t, "revisions": [{"slots": {"main": {"content": text}}}]}]
    elif prop == "langlinks":
        for i, t in enumerate(titles):
            pg = {"pageid": i + 1, "title": t}
            if t in EN_TR:
                pg["langlinks"] = [{"lang": "tr", "title": EN_TR[t]}]
            pages.append(pg)
    elif prop == "extracts|pageimages|pageprops":
        for i, t in enumerate(titles):
            d = TR_PAGES.get(t)
            if not d:
                pages.append({"title": t, "missing": True})
                continue
            pg = {"pageid": i + 1, "title": t, "extract": _intro(d)}
            if d["image"]:
                pg["thumbnail"] = {"source": f"https://upload.wikimedia.org/x/1280px-{d['image']}", "width": 1280, "height": 853}
                pg["pageimage"] = d["image"]
            if d["disamb"]:
                pg["pageprops"] = {"disambiguation": ""}
            pages.append(pg)
    elif prop == "categories|extracts":
        for i, t in enumerate(titles):
            d = TR_PAGES.get(t)
            if not d:
                pages.append({"title": t, "missing": True})
                continue
            pages.append({"pageid": i + 1, "title": t, "extract": d["lead"][0][:300],
                          "categories": [{"ns": 14, "title": c} for c in d["cats"]]})
    elif prop == "extracts":
        d = TR_PAGES.get(titles[0])
        pages = [{"pageid": 1, "title": titles[0], "extract": _full(d)}] if d else [{"title": titles[0], "missing": True}]
    elif prop == "imageinfo":
        pages = [{"title": titles[0], "missing": True, "imagerepository": "shared", "imageinfo": [{
            "descriptionurl": "https://commons.wikimedia.org/wiki/" + titles[0],
            "extmetadata": {"Artist": {"value": "<a href=\"#\">Ayşe Çelik</a>"},
                            "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}]
    return {"batchcomplete": True, "query": {"pages": pages}}

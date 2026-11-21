import json
import os
import random
import re
import shutil
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

from tarihrss import article, config, feed, pipeline, sources, store, textutil, wiki
from tests import fake_wiki

NS = {"c": "http://purl.org/rss/1.0/modules/content/", "a": "http://www.w3.org/2005/Atom"}
QUIET = lambda *a, **k: None


def read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def fake_api():
    return wiki.Api(transport=fake_wiki.transport, sleep=lambda s: None, min_interval=0)


def flaky_api(fail):
    """fail(lang, params) doğruysa ağ hatası verir (sabah çalışmasındaki geçici arızayı taklit eder)."""
    def transport(lang, p):
        if fail(lang, p):
            raise urllib.error.URLError("geçici kesinti")
        return fake_wiki.transport(lang, p)
    return wiki.Api(transport=transport, sleep=lambda s: None, min_interval=0, retries=2)


class TextTests(unittest.TestCase):
    def test_title_never_exceeds_70(self):
        rng = random.Random(1)
        words = "Büyük Osmanlı İmparatorluğu'nun Doğu Avrupa'daki ilk resmî sefer ve ç ğ ı ö ş ü kuşatma antlaşması imzalandı".split()
        for _ in range(600):
            sent = " ".join(rng.choice(words) for _ in range(rng.randint(2, 30)))
            name = " ".join(rng.choice(words) for _ in range(rng.randint(1, 14)))
            for kind in ("olay", "dogum", "olum", "ozel_gun"):
                for el in (True, False):
                    t = textutil.make_title(kind, None if kind == "ozel_gun" else rng.choice([-44, 476, 1453, 2001]), name, sent if kind == "olay" else "", el)
                    self.assertLessEqual(len(t), 70, t)
                    self.assertTrue(t.strip())

    def test_turkish_helpers(self):
        self.assertEqual(textutil.tr_upper_first("istanbul"), "İstanbul")
        self.assertEqual(textutil.slugify("Çanakkale Savaşı: Gelibolu'da İlk Gün"), "canakkale-savasi-gelibolu-da-ilk-gun")
        self.assertEqual(textutil.date_phrase(18, 11, -44), "18 Kasım M.Ö. 44")

    def test_sentence_split_keeps_abbreviations(self):
        t = "Ada Demir (d. 1860, İstanbul), Türk şairdir. M.Ö. 44 yılında bir şey oldu. Son cümle burada."
        self.assertEqual(textutil.sentences(t)[0], "Ada Demir (d. 1860, İstanbul), Türk şairdir.")
        self.assertEqual(len(textutil.sentences(t)), 3)

    def test_first_sentences_split_loses_nothing(self):
        text = " ".join(f"Bu {i}. cümle yeterince uzun ve anlamlı bir cümledir." for i in range(1, 15))
        summ, rest = textutil.split_first_sentences(text, 380)
        self.assertLessEqual(len(summ), 380)
        self.assertTrue(rest)
        self.assertEqual(textutil.norm_space(summ + " " + rest), textutil.norm_space(text))
        long_one = "Çok " * 200 + "uzun tek cümle."
        summ, rest = textutil.split_first_sentences(long_one, 380)
        self.assertTrue(summ.endswith("…"))
        self.assertEqual(rest, long_one.strip())              # kısaltılan özet için paragraf eksiksiz kalan olarak döner

    def test_parse_year(self):
        self.assertEqual(sources.parse_year("MÖ 44"), -44)
        self.assertEqual(sources.parse_year("44 BC"), -44)
        self.assertEqual(sources.parse_year("1453"), 1453)
        self.assertIsNone(sources.parse_year("Napoleon"))

    def test_parse_day_pages(self):
        tr = sources.parse_day_wikitext(fake_wiki.TR_DAY, "tr", 11, 18)
        kinds = [(c["kind"], c["year"]) for c in tr]
        self.assertIn(("olay", 1918), kinds)
        self.assertIn(("olay", -44), kinds)
        self.assertIn(("dogum", 1860), kinds)
        self.assertIn(("olum", 1923), kinds)
        self.assertEqual(len(tr), 8)                      # tatil/özel günler de alınır
        self.assertIn(("ozel_gun", None), kinds)
        lv = next(c for c in tr if c["year"] == 1918)
        self.assertEqual(lv["links"], ["Letonya", "Rusya İmparatorluğu"])
        self.assertNotIn("<ref", lv["text"])
        en = sources.parse_day_wikitext(fake_wiki.EN_DAY, "en", 11, 18)
        self.assertEqual({c["kind"] for c in en}, {"olay", "dogum", "olum"})


class ArticleTextTests(unittest.TestCase):
    def test_short_lines_and_nested_sections_kept(self):
        text = ("Giriş paragrafı yeterince uzun bir cümledir.\nKısa\n== Tarihçe ==\nİlk\nSon satır burada.\n"
                "=== Alt ===\nAlt metin satırı.\n== Kaynakça ==\nKaynak 1\n=== Kitaplar ===\nKitap A\n"
                "== Etkiler ==\nEtki metni burada.\n== Boş Ana ==\n=== Çocuk ===\nÇocuk metni burada.\n")
        lead, secs = article.split_sections(text)
        self.assertEqual(lead, ["Giriş paragrafı yeterince uzun bir cümledir.", "Kısa"])
        self.assertEqual([x["title"] for x in secs], ["Tarihçe", "Alt", "Etkiler", "Boş Ana", "Çocuk"])
        self.assertEqual(secs[0]["paras"], ["İlk", "Son satır burada."])      # kısa satırlar atılmaz
        self.assertEqual(secs[3]["paras"], [])                                # altında metin olan başlık korunur

    def test_list_rendering(self):
        html = article.paras_html(["Bir", "İki", "Üç", "Bu bir cümledir."])
        self.assertIn("<ul>", html)
        self.assertEqual(html.count("<li>"), 3)
        self.assertIn("<p>Bu bir cümledir.</p>", html)
        self.assertNotIn("<ul>", article.paras_html(["Bir", "İki", "Bu bir cümledir."]))

    def test_unique_slug_never_overwrites(self):
        rec = {"slug": "2026-11-18-x", "content_file": "data/content/2026-11-18-x.html", "link": "u"}
        article.unique_slug(rec, {"2026-11-18-x", "2026-11-18-x-2"})
        self.assertEqual(rec["slug"], "2026-11-18-x-3")
        self.assertEqual(rec["content_file"], "data/content/2026-11-18-x-3.html")
        self.assertTrue(rec["link"].endswith("/makale/2026-11-18-x-3.html"))


class AuditTests(unittest.TestCase):
    def test_realistic_wikitext(self):
        tr = ("== Olaylar ==\n* [[1928]] - {{nowrap|[[Walt Disney]]'in}} filmi gösterime girdi.<ref>x</ref>\n"
              "== Doğumlar ==\n* [[1787]] - [[Louis Daguerre]], Fransız sanatçı ([[ö. 1851]])\n== Kaynakça ==\n* [[1999]] - [[Hayır]] alınmaz burada.\n")
        c = sources.parse_day_wikitext(tr, "tr", 11, 18)
        self.assertEqual([x["year"] for x in c], [1928, 1787])
        self.assertEqual(c[0]["links"], ["Walt Disney"])               # şablon içindeki bağlantı/içerik korunur
        self.assertIn("Walt Disney'in filmi", c[0]["text"])
        self.assertEqual(c[1]["links"], ["Louis Daguerre"])            # '(ö. 1851)' sahte bağlantısı yok

    def test_non_person_birth_is_not_published(self):
        pipeline.run(root=self.root, today=date(2026, 11, 18), api=fake_api(), now=self.now, log=QUIET)
        arts = store.load(self.root)
        self.assertNotIn("Türk", {a["topic_title"] for a in arts["articles"]})      # adı bağlantısız doğum satırı
        why = {v.get("r") for v in arts["days"]["2026-11-18"].values() if v["s"] == "skip"}
        self.assertIn("kisi_degil", why)
        self.assertIn("tr_madde_yok", why)

    def setUp(self):
        self.root = tempfile.mkdtemp()
        shutil.copytree("assets", os.path.join(self.root, "assets"))
        self.now = datetime(2026, 11, 18, 3, 17, tzinfo=timezone.utc)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_math_only_lines_dropped_text_kept(self):
        self.assertFalse(article._keep_line("{\\displaystyle E=mc^{2}}"))
        self.assertTrue(article._keep_line("Formül {\\displaystyle E=mc^{2}} enerjiyi açıklar."))

    def test_generated_html_is_well_formed_and_feed_capped(self):
        from html.parser import HTMLParser
        pipeline.run(root=self.root, today=date(2026, 11, 18), api=fake_api(), now=self.now, log=QUIET)

        class Bal(HTMLParser):
            VOID = {"img", "meta", "link", "br", "hr"}

            def __init__(self):
                super().__init__()
                self.stack, self.bad = [], []

            def handle_starttag(self, tag, attrs):
                if tag not in self.VOID:
                    self.stack.append(tag)

            def handle_startendtag(self, tag, attrs):
                pass                                           # <img ... /> kendi kendini kapatır

            def handle_endtag(self, tag):
                if tag in self.VOID:
                    return
                if not self.stack or self.stack.pop() != tag:
                    self.bad.append(tag)
        for a in store.load(self.root)["articles"]:
            for path in (a["content_file"], os.path.join("makale", a["slug"] + ".html")):
                p = Bal()
                p.feed(read(os.path.join(self.root, path)))
                self.assertEqual((p.stack, p.bad), ([], []), path)
        old, config.FEED_MAX_MB = config.FEED_MAX_MB, 0.02          # ~20 KB: yalnızca en yeni öğeler sığar
        try:
            n = feed.write_all(self.root, store.load(self.root)["articles"], self.now, QUIET)
        finally:
            config.FEED_MAX_MB = old
        self.assertGreaterEqual(n, 1)
        self.assertLess(read(os.path.join(self.root, "rss.xml")).count("<item>"), len(store.load(self.root)["articles"]))
        ET.fromstring(read(os.path.join(self.root, "rss.xml")).encode("utf-8"))


class CuratedSourceTests(unittest.TestCase):
    def test_bold_year_li_and_default_kind(self):
        c = sources.parse_day_wikitext(fake_wiki.TBUGUN_TR, "tr", 11, 18, default_kind="olay")
        self.assertEqual([(x["kind"], x["year"]) for x in c], [("olay", 1601), ("olay", 1927)])
        self.assertEqual(c[0]["links"], ["Kanije Savunması"])
        self.assertEqual(sources.parse_day_wikitext("* [[1601]] – [[X]] bir olay yaşandı burada.", "tr", 11, 18), [])  # başlıksızda tür yok
        c = sources.parse_day_wikitext("# '''1601 –''' [[Kanije Savunması]] kazanıldı bugün.", "tr", 11, 18, default_kind="olay")
        self.assertEqual(c[0]["year"], 1601)

    def test_pool_has_curated_items_and_survives_source_failures(self):
        pool = sources.build_pool(fake_api(), 11, 18, QUIET)
        got = {(c["lang"], c["year"]) for c in pool}
        self.assertTrue({("tr", 1601), ("tr", 1927), ("en", 1865)} <= got)
        failed = []
        down = flaky_api(lambda l, p: p.get("action") == "expandtemplates" or "Selected" in str(p.get("titles")))
        pool = sources.build_pool(down, 11, 18, QUIET, failed)
        self.assertEqual(failed, [])                                   # ek kaynak arızası gün sayfası arızası sayılmaz
        self.assertFalse(any(c["year"] == 1601 for c in pool))
        self.assertTrue(any(c["year"] == 1918 for c in pool))

    def test_missing_template_is_ignored(self):
        self.assertEqual(sources.extra_sources(11, 18)[0][2], "{{Tarihte bugün/18 Kasım}}")
        pool = sources.build_pool(fake_api(), 11, 18, QUIET)           # 18 Kasım şablonu var
        self.assertTrue(pool)
        # kırmızı bağlantı çıktısı ('[[:Şablon:…]]') aday üretmez
        self.assertEqual(sources.parse_day_wikitext("[[:Şablon:Tarihte bugün/19 Kasım]]", "tr", 11, 19, default_kind="olay"), [])


class ApiTests(unittest.TestCase):
    def test_retry_then_success(self):
        calls = {"n": 0}

        def flaky(lang, p):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.HTTPError("u", 503, "x", {"Retry-After": "1"}, None)
            return {"query": {"pages": []}}
        api = wiki.Api(transport=flaky, sleep=lambda s: None, min_interval=0)
        self.assertEqual(api.query("tr", titles="x"), {"pages": []})
        self.assertEqual(calls["n"], 3)

    def test_gives_up_with_wikierror(self):
        def down(lang, p):
            raise urllib.error.URLError("yok")
        with self.assertRaises(wiki.WikiError):
            wiki.Api(transport=down, sleep=lambda s: None, min_interval=0, retries=3).query("tr", titles="x")

    def test_continue_merging(self):
        seq = [{"continue": {"llcontinue": "a"}, "query": {"pages": [{"title": "X", "langlinks": [{"lang": "tr", "title": "1"}]}]}},
               {"query": {"pages": [{"title": "X", "langlinks": [{"lang": "de", "title": "2"}]}]}}]
        api = wiki.Api(transport=lambda l, p: seq.pop(0), sleep=lambda s: None, min_interval=0)
        q = api.query("en", prop="langlinks", titles="X")
        self.assertEqual(len(q["pages"][0]["langlinks"]), 2)

    def test_incomplete_read_is_retried(self):
        import http.client
        calls = {"n": 0}

        def flaky(lang, p):
            calls["n"] += 1
            if calls["n"] < 2:
                raise http.client.IncompleteRead(b"x")
            return {"query": {"pages": []}}
        api = wiki.Api(transport=flaky, sleep=lambda s: None, min_interval=0)
        self.assertEqual(api.query("tr", titles="x"), {"pages": []})

    def test_api_error_raises(self):
        api = wiki.Api(transport=lambda l, p: {"error": {"code": "badvalue", "info": "x"}}, sleep=lambda s: None, min_interval=0)
        with self.assertRaises(wiki.WikiError):
            api.query("en", titles="x")


class FeedTests(unittest.TestCase):
    def test_cdata_escape_and_valid_xml(self):
        rec = {"id": "t1", "title": "Başlık ç ğ ı İ ö ş ü & <test>", "link": "https://x/y", "pub": "2026-11-18T03:00:00Z",
               "description": "Açıklama & \x0b kontrol", "categories": ["Olay"], "date": "2026-11-18",
               "image": {"url": "https://x/i.jpg?a=1&b=2", "width": 10, "height": 5}}
        xml = feed.build_rss([rec], {"t1": "<p>içerik ]]> sonu</p>"}, "https://x/rss.xml", datetime(2026, 11, 18, tzinfo=timezone.utc))
        root = ET.fromstring(xml.encode("utf-8"))
        item = root.find("channel/item")
        self.assertEqual(item.find("title").text, "Başlık ç ğ ı İ ö ş ü & <test>")
        self.assertIn("]]> sonu", item.find("c:encoded", NS).text)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        shutil.copytree("assets", os.path.join(self.root, "assets"))
        self.now = datetime(2026, 11, 18, 3, 17, tzinfo=timezone.utc)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_day(self, day=date(2026, 11, 18), per_day=3):
        return pipeline.run(root=self.root, today=day, per_day=per_day, api=fake_api(), now=self.now, log=QUIET)

    def test_end_to_end(self):
        res = self.run_day()
        self.assertEqual(res["new"], 3, res)
        rss = read(os.path.join(self.root, "rss.xml"))
        root = ET.fromstring(rss.encode("utf-8"))
        self.assertEqual(root.attrib["version"], "2.0")
        items = root.findall("channel/item")
        self.assertEqual(len(items), 3)
        guids = [i.find("guid").text for i in items]
        self.assertEqual(len(set(guids)), 3)
        for i in items:
            title = i.find("title").text
            self.assertLessEqual(len(title), 70)
            body = i.find("c:encoded", NS).text
            self.assertNotIn("<h1", body.lower())
            self.assertIn("<h2>Kısa Özet</h2>", body)
            self.assertIn("<h2>Kaynaklar</h2>", body)
            self.assertTrue(body.lstrip().startswith('<div class="separator"'), "kapak görseli en üstte olmalı")
            self.assertIn('alt="', body)
            self.assertRegex(i.find("pubDate").text, r"^\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} \+0000$")
            self.assertLessEqual(len(i.find("description").text), 155)
            self.assertNotIn("&#x27;", body)
            self.assertGreater(len(body), 2500)
        self.assertIn("ç, ğ, ı, İ, ö, ş ve ü", rss)                       # Türkçe karakterler eksiksiz
        # yalnızca rss.xml üretilir: 'feed' ve sitemap.xml yok
        self.assertFalse(os.path.exists(os.path.join(self.root, "feed")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "sitemap.xml")))
        self.assertEqual(root.find("channel/a:link", NS).attrib["href"], "https://xmifrmx.github.io/makale/rss.xml")
        self.assertTrue(all(i.find("link").text.startswith("https://xmifrmx.github.io/makale/makale/") for i in items))
        pages = os.listdir(os.path.join(self.root, "makale"))
        self.assertEqual(len([p for p in pages if p.endswith(".html")]), 3)
        topics = [a["topic_key"] for a in store.load(self.root)["articles"]]
        self.assertEqual(len(set(topics)), 3)

    def test_full_article_text_included(self):
        self.run_day(per_day=None)
        arts = store.load(self.root)["articles"]
        self.assertGreaterEqual(len(arts), 6)
        for a in arts:
            body = read(os.path.join(self.root, a["content_file"]))
            d = fake_wiki.TR_PAGES[a["topic_title"]]
            skipped = {"Kaynakça", "Kitaplar"}
            for para in d["lead"][1:] + [p for n, ps, lvl in d["sections"] if n not in skipped for p in ps]:
                self.assertIn(para.replace("&", "&amp;"), body)      # kısa satırlar dahil her paragraf var
            for sent in textutil.sentences(d["lead"][0]):            # ilk paragraf: özet + kalanı = hiçbir cümle kaybolmaz
                self.assertIn(sent, body)
            self.assertNotIn("<h3>Kaynakça</h3>", body)
            self.assertNotIn("Kaynak kitap", body)                   # atlanan bölümün alt başlığı da atlanır
            self.assertEqual(a["gaps"], [])
            self.assertTrue(a["complete"])
        somme = read(os.path.join(self.root, next(a for a in arts if a["topic_title"] == "Somme Muharebesi")["content_file"]))
        self.assertIn("<h4>Komutanlar</h4>", somme)
        block = somme.split("<h4>Komutanlar</h4>")[1].split("<h")[0]
        self.assertEqual(block.count("<li>"), 4)                     # Douglas Haig … kısa satırlar liste olarak korunur
        kadife = read(os.path.join(self.root, next(a for a in arts if a["topic_title"] == "Kadife Devrim")["content_file"]))
        self.assertIn("<h3>Etkileri</h3>", kadife)                   # kendi metni olmayan ana başlık korunur
        self.assertIn("<h4>Siyasi Sonuçlar</h4>", kadife)

    def test_unlimited_day_takes_every_suitable_item_once(self):
        res = self.run_day(per_day=None)
        arts = store.load(self.root)["articles"]
        self.assertEqual(res["new"], len(arts))
        kinds = {a["kind"] for a in arts}
        self.assertEqual(kinds, {"olay", "dogum", "olum", "ozel_gun"})
        titles = {a["topic_title"] for a in arts}
        self.assertTrue({"Somme Muharebesi", "Kadife Devrim", "Ada Demir", "Mehmet Kaya", "W. S. Gilbert",
                         "Aleksandr Orlov", "Letonya Bağımsızlık Günü", "William Caxton",
                         "Kanije Savunması", "Ankara Radyosu", "Mark Twain"} <= titles, titles)
        cax = next(a for a in arts if a["topic_title"] == "William Caxton")
        self.assertEqual(cax["kind"], "olay")                                # İngilizce olay: elenmez, çevrilmemiş cümle uydurulmaz
        self.assertIn("maddesiyle ilişkilendirilen", read(os.path.join(self.root, cax["content_file"])))
        hol = next(a for a in arts if a["kind"] == "ozel_gun")
        self.assertIsNone(hol["year"])
        self.assertIn("Özel Gün", hol["categories"])
        self.assertLessEqual(len(hol["title"]), 70)
        self.assertEqual(len(titles), len({a["topic_key"] for a in arts}))   # aynı konu iki kez yok (Somme tr+en)
        self.assertEqual(len({a["slug"] for a in arts}), len(arts))
        again = self.run_day(per_day=None)
        self.assertEqual(again["new"], 0)                                    # ikinci çalışma: yeni bir şey yok
        self.assertEqual(len(store.load(self.root)["articles"]), len(arts))

    def test_second_run_adds_only_missing(self):
        later = self.now + timedelta(hours=8, minutes=30)                    # 14:47 TSİ
        flaky = flaky_api(lambda l, p: p.get("prop") == "extracts|info" and p.get("titles") == "Kadife Devrim")
        r1 = pipeline.run(root=self.root, today=date(2026, 11, 18), api=flaky, now=self.now, log=QUIET)
        self.assertEqual(r1["pending"], 1)
        before = {a["id"]: a for a in store.load(self.root)["articles"]}
        self.assertNotIn("Kadife Devrim", {a["topic_title"] for a in before.values()})
        bodies = {i: read(os.path.join(self.root, a["content_file"])) for i, a in before.items()}
        r2 = pipeline.run(root=self.root, today=date(2026, 11, 18), api=fake_api(), now=later, log=QUIET)
        self.assertEqual((r2["new"], r2["updated"], r2["pending"]), (1, 0, 0), r2)
        after = {a["id"]: a for a in store.load(self.root)["articles"]}
        self.assertEqual(len(after), len(before) + 1)
        for i, a in before.items():                                          # sabahkiler aynen kalır
            self.assertEqual(after[i]["pub"], a["pub"])
            self.assertEqual(read(os.path.join(self.root, a["content_file"])), bodies[i])
        newest = next(a for a in after.values() if a["id"] not in before)
        self.assertEqual(newest["topic_title"], "Kadife Devrim")
        self.assertEqual(newest["pub"], "2026-11-18T11:47:00Z")               # yeni öğe RSS'in en üstünde
        items = ET.fromstring(read(os.path.join(self.root, "rss.xml")).encode("utf-8")).findall("channel/item")
        self.assertEqual(len(items), len(after))
        self.assertEqual(len({i.find("guid").text for i in items}), len(items))

    def test_second_run_completes_gaps_in_one_piece(self):
        later = self.now + timedelta(hours=8, minutes=30)
        flaky = flaky_api(lambda l, p: p.get("prop") == "imageinfo")
        pipeline.run(root=self.root, today=date(2026, 11, 18), api=flaky, now=self.now, log=QUIET)
        before = {a["id"]: a for a in store.load(self.root)["articles"]}
        gapped = [a for a in before.values() if a["gaps"]]
        self.assertTrue(gapped)
        self.assertTrue(all(a["gaps"] == ["gorsel_bilgisi"] and not a["complete"] for a in gapped))
        self.assertNotIn("Ayşe Çelik", read(os.path.join(self.root, gapped[0]["content_file"])))
        r2 = pipeline.run(root=self.root, today=date(2026, 11, 18), api=fake_api(), now=later, log=QUIET)
        self.assertEqual(r2["new"], 0)
        self.assertEqual(r2["updated"], len(gapped))
        after = {a["id"]: a for a in store.load(self.root)["articles"]}
        self.assertEqual(set(after), set(before))                            # aynı kimlikler: yeni/çift kayıt yok
        for a in gapped:
            n = after[a["id"]]
            self.assertEqual((n["slug"], n["pub"], n["link"]), (a["slug"], a["pub"], a["link"]))
            self.assertEqual(n["gaps"], [])
            self.assertTrue(n["complete"] and n["updated"])
            body = read(os.path.join(self.root, n["content_file"]))
            self.assertIn("Ayşe Çelik", body)                                # tek parça, eksiksiz yeniden derleme
            self.assertIn("<h2>Kısa Özet</h2>", body)
            self.assertIn("Ayşe Çelik", read(os.path.join(self.root, "makale", n["slug"] + ".html")))
        rss = read(os.path.join(self.root, "rss.xml"))
        self.assertEqual(rss.count("<item>"), len(after))
        self.assertEqual(r2["errors"], [])

    def test_source_change_rebuilds_article_in_place(self):
        self.run_day(per_day=None)
        before = next(a for a in store.load(self.root)["articles"] if a["topic_title"] == "Somme Muharebesi")
        fake_wiki.TR_PAGES["Somme Muharebesi"]["sections"].append(
            ("Yeni Bölüm", ["Vikipedi'de öğleden sonra eklenen yeni paragraf yeterince uzun bir cümledir."], 2))
        fake_wiki.REV["Somme Muharebesi"] = 2
        later = self.now + timedelta(hours=8, minutes=30)
        try:
            r2 = pipeline.run(root=self.root, today=date(2026, 11, 18), api=fake_api(), now=later, log=QUIET)
            # kaynak aynı kaldıysa (rev=2) sonraki çalışma hiçbir şeyi yeniden derlemez
            r3 = pipeline.run(root=self.root, today=date(2026, 11, 18), api=fake_api(), now=later, log=QUIET)
        finally:
            fake_wiki.TR_PAGES["Somme Muharebesi"]["sections"].pop()
            fake_wiki.REV.clear()
        self.assertEqual((r2["new"], r2["updated"]), (0, 1), r2)
        self.assertEqual((r3["new"], r3["updated"]), (0, 0), r3)
        arts = store.load(self.root)["articles"]
        after = next(a for a in arts if a["topic_title"] == "Somme Muharebesi")
        self.assertEqual((after["id"], after["pub"], after["slug"]), (before["id"], before["pub"], before["slug"]))
        self.assertEqual(after["rev"], 2)
        self.assertIn("öğleden sonra eklenen yeni paragraf", read(os.path.join(self.root, after["content_file"])))
        self.assertEqual(sum(1 for a in arts if a["topic_title"] == "Somme Muharebesi"), 1)

    def test_random_outages_converge_to_clean_run(self):
        """Sabah rastgele API arızaları olsa bile 14:47 çalışması sonucu arızasız tek çalışmayla aynı kümeye getirir."""
        clean = {a["topic_key"] for a in (self.run_day(per_day=None), store.load(self.root))[1]["articles"]}
        for seed in range(8):
            root = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, root, True)
            shutil.copytree("assets", os.path.join(root, "assets"))
            rng = random.Random(seed)
            flaky = flaky_api(lambda l, p: rng.random() < 0.3)
            pipeline.run(root=root, today=date(2026, 11, 18), api=flaky, now=self.now, log=QUIET)
            later = self.now + timedelta(hours=8, minutes=30)
            pipeline.run(root=root, today=date(2026, 11, 18), api=fake_api(), now=later, log=QUIET)
            arts = store.load(root)["articles"]
            self.assertEqual({a["topic_key"] for a in arts}, clean, seed)
            self.assertEqual(len(arts), len({a["id"] for a in arts}), seed)
            self.assertTrue(all(a["complete"] for a in arts), seed)
            third = pipeline.run(root=root, today=date(2026, 11, 18), api=fake_api(), now=later, log=QUIET)
            self.assertEqual((third["new"], third["updated"], third["pending"]), (0, 0, 0), (seed, third))
            self.assertEqual(read(os.path.join(root, "rss.xml")).count("<item>"), len(clean), seed)

    def test_legacy_site_url_is_migrated(self):
        self.run_day(per_day=None)
        p = os.path.join(self.root, "data", "index.json")
        data = json.loads(read(p))
        old = "https://umutevicom-commits.github.io/tarih"
        for a in data["articles"]:
            a["link"] = f"{old}/makale/{a['slug']}.html"
        write(p, json.dumps(data, ensure_ascii=False))
        self.run_day(per_day=None)
        arts = store.load(self.root)["articles"]
        self.assertTrue(all(a["link"] == f"{config.SITE_URL}/makale/{a['slug']}.html" for a in arts))
        self.assertNotIn("umutevicom", read(os.path.join(self.root, "rss.xml")))
        self.assertNotIn("umutevicom", read(os.path.join(self.root, "makale", arts[0]["slug"] + ".html")))

    def test_feed_always_holds_the_whole_latest_day(self):
        self.run_day(per_day=None)
        arts = store.load(self.root)["articles"]
        old, config.FEED_ITEMS = config.FEED_ITEMS, 2
        try:
            n = feed.write_all(self.root, arts, self.now, QUIET)
        finally:
            config.FEED_ITEMS = old
        self.assertEqual(n, len(arts))

    def test_idempotent_same_day_and_no_duplicates_later(self):
        self.assertEqual(self.run_day()["new"], 3)
        self.assertEqual(self.run_day()["new"], 0)               # aynı gün ikinci çalışma: üretmez
        res = self.run_day(per_day=6)                            # hedef artarsa yalnızca eksik kadar, tekrarsız
        topics = [a["topic_key"] for a in store.load(self.root)["articles"]]
        self.assertEqual(len(topics), len(set(topics)))
        self.assertLessEqual(res["new"], 3)

    def test_api_down_keeps_existing_feed(self):
        self.run_day()
        before = read(os.path.join(self.root, "rss.xml")).count("<item>")

        def down(lang, p):
            raise urllib.error.URLError("kapalı")
        api = wiki.Api(transport=down, sleep=lambda s: None, min_interval=0, retries=2)
        res = pipeline.run(root=self.root, today=date(2026, 11, 19), per_day=3, api=api, now=self.now, log=QUIET)
        self.assertEqual(res["new"], 0)
        self.assertTrue(res["errors"] or res["today_total"] == 0)
        after = read(os.path.join(self.root, "rss.xml")).count("<item>")
        self.assertEqual(before, after)                          # RSS bozulmadı

    def test_corrupt_index_recovers_from_backup(self):
        self.run_day(per_day=2)
        self.run_day(per_day=3)                                  # ikinci kayıt .bak üretir
        p = os.path.join(self.root, "data", "index.json")
        open(p, "w").close(); write(p, "{bozuk json")
        data = store.load(self.root, QUIET)
        self.assertGreaterEqual(len(data["articles"]), 2)

    def test_missing_image_uses_fallback_cover(self):
        for a in fake_wiki.TR_PAGES.values():
            a["image"] = None
        try:
            res = self.run_day()
        finally:
            fake_wiki.TR_PAGES["Mehmet Kaya"]["image"] = None   # zaten None
            for k, v in fake_wiki.TR_PAGES.items():
                if k != "Mehmet Kaya" and k != "Aleksandr Orlov":
                    v["image"] = "Kapak_gorsel.jpg"
            fake_wiki.TR_PAGES["Aleksandr Orlov"]["image"] = "Orlov_flag_logo.png"
        self.assertGreaterEqual(res["new"], 1)
        arts = store.load(self.root)["articles"]
        self.assertTrue(all(a["image"]["fallback"] for a in arts))
        self.assertIn("kapak-varsayilan.svg", arts[0]["image"]["url"])


if __name__ == "__main__":
    unittest.main()

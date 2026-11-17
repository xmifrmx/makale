import json
import os
import random
import re
import shutil
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

from tarihrss import config, feed, pipeline, sources, store, textutil, wiki
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


class TextTests(unittest.TestCase):
    def test_title_never_exceeds_70(self):
        rng = random.Random(1)
        words = "Büyük Osmanlı İmparatorluğu'nun Doğu Avrupa'daki ilk resmî sefer ve ç ğ ı ö ş ü kuşatma antlaşması imzalandı".split()
        for _ in range(600):
            sent = " ".join(rng.choice(words) for _ in range(rng.randint(2, 30)))
            name = " ".join(rng.choice(words) for _ in range(rng.randint(1, 14)))
            for kind in ("olay", "dogum", "olum"):
                for el in (True, False):
                    t = textutil.make_title(kind, rng.choice([-44, 476, 1453, 2001]), name, sent if kind == "olay" else "", el)
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
        self.assertEqual(len(tr), 6)                      # 'Tatiller' bölümü alınmaz
        lv = next(c for c in tr if c["year"] == 1918)
        self.assertEqual(lv["links"], ["Letonya", "Rusya İmparatorluğu"])
        self.assertNotIn("<ref", lv["text"])
        en = sources.parse_day_wikitext(fake_wiki.EN_DAY, "en", 11, 18)
        self.assertEqual({c["kind"] for c in en}, {"olay", "dogum", "olum"})


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
        # 'feed' ayrı dosya, kendi self-link'i ile geçerli XML
        feed_root = ET.fromstring(read(os.path.join(self.root, "feed"), "rb"))
        self.assertTrue(feed_root.find("channel/a:link", NS).attrib["href"].endswith("/tarih/feed"))
        ET.parse(os.path.join(self.root, "sitemap.xml"))
        pages = os.listdir(os.path.join(self.root, "makale"))
        self.assertEqual(len([p for p in pages if p.endswith(".html")]), 3)
        topics = [a["topic_key"] for a in store.load(self.root)["articles"]]
        self.assertEqual(len(set(topics)), 3)

    def test_full_article_text_included(self):
        self.run_day()
        for a in store.load(self.root)["articles"]:
            body = read(os.path.join(self.root, a["content_file"]))
            d = fake_wiki.TR_PAGES[a["topic_title"]]
            for para in d["lead"][1:] + [p for n, ps in d["sections"] if n != "Kaynakça" for p in ps]:
                self.assertIn(para.replace("&", "&amp;"), body)      # lead[0] özette; kalan her paragraf var
            self.assertIn(d["lead"][0][:60], body)
            self.assertNotIn("<h3>Kaynakça</h3>", body)

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

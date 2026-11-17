"""RSS 2.0 (rss.xml + feed), sitemap.xml ve makale sayfalarının üretimi."""
from __future__ import annotations
import html
import json
import os
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape, quoteattr

from . import config
from .textutil import xml_clean

esc = html.escape


def _dt(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def rfc822(dt):
    return format_datetime(dt.astimezone(timezone.utc), usegmt=False).replace("-0000", "+0000")


def cdata(s):
    return "<![CDATA[" + xml_clean(s).replace("]]>", "]]]]><![CDATA[>") + "]]>"


def build_rss(records, contents, self_url, now):
    items = []
    for r in records:
        body = contents.get(r["id"])
        if not body:
            continue
        img = r["image"]
        cats = "".join(f"      <category>{escape(xml_clean(c))}</category>\n" for c in r["categories"])
        items.append(
            "    <item>\n"
            f"      <title>{escape(xml_clean(r['title']))}</title>\n"
            f"      <link>{escape(r['link'])}</link>\n"
            f"      <guid isPermaLink=\"false\">{escape(r['id'])}</guid>\n"
            f"      <pubDate>{rfc822(_dt(r['pub']))}</pubDate>\n"
            f"      <dc:creator>Tarihte Bugün</dc:creator>\n"
            f"{cats}"
            f"      <description>{escape(xml_clean(r['description']))}</description>\n"
            f"      <media:content url={quoteattr(img['url'])} medium=\"image\" width=\"{img['width']}\" height=\"{img['height']}\" />\n"
            f"      <content:encoded>{cdata(body)}</content:encoded>\n"
            "    </item>\n")
    last = rfc822(now)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:media="http://search.yahoo.com/mrss/">\n'
        "  <channel>\n"
        f"    <title>{escape(config.SITE_TITLE)}</title>\n"
        f"    <link>{escape(config.SITE_URL)}/</link>\n"
        f"    <description>{escape(config.SITE_DESC)}</description>\n"
        "    <language>tr</language>\n"
        f"    <lastBuildDate>{last}</lastBuildDate>\n"
        "    <ttl>720</ttl>\n"
        "    <generator>tarihrss (GitHub Actions)</generator>\n"
        f'    <atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml" />\n'
        + "".join(items) + "  </channel>\n</rss>\n")


def build_sitemap(records):
    records = records[:config.SITEMAP_MAX]          # sitemap protokolü: en fazla 50.000 adres (kayıtlar yeniden eskiye sıralı)
    urls = "".join(f"  <url><loc>{escape(r['link'])}</loc><lastmod>{r['date']}</lastmod></url>\n" for r in records)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n")


PAGE_CSS = ("body{font:18px/1.7 system-ui,'Segoe UI',Roboto,sans-serif;margin:0;background:#fafafa;color:#1b1b1b}"
            "main{max-width:760px;margin:auto;padding:24px 18px 60px}img{max-width:100%;height:auto;border-radius:10px}"
            "a{color:#0b57d0}h1{line-height:1.25}h2{margin-top:2em}.meta{color:#666;font-size:.9em}"
            "@media(prefers-color-scheme:dark){body{background:#121212;color:#eaeaea}a{color:#8ab4f8}.meta{color:#aaa}}")


def build_page(r, body):
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": r["title"],
          "description": r["description"], "inLanguage": "tr", "datePublished": r["pub"],
          "image": [r["image"]["url"]], "mainEntityOfPage": r["link"],
          "author": {"@type": "Organization", "name": "Tarihte Bugün"},
          "publisher": {"@type": "Organization", "name": "Tarihte Bugün"}}
    ld_json = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    t, d = esc(r["title"], quote=True), esc(r["description"], quote=True)
    return (
        "<!DOCTYPE html>\n<html lang=\"tr\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{esc(r['title'])}</title>\n<meta name=\"description\" content=\"{d}\">\n"
        f"<link rel=\"canonical\" href=\"{esc(r['link'], quote=True)}\">\n"
        f"<link rel=\"alternate\" type=\"application/rss+xml\" title=\"{esc(config.SITE_TITLE, quote=True)}\" href=\"{config.SITE_URL}/rss.xml\">\n"
        f"<meta property=\"og:type\" content=\"article\"><meta property=\"og:title\" content=\"{t}\">\n"
        f"<meta property=\"og:description\" content=\"{d}\"><meta property=\"og:image\" content=\"{esc(r['image']['url'], quote=True)}\">\n"
        f"<meta property=\"og:locale\" content=\"tr_TR\">\n<style>{PAGE_CSS}</style>\n"
        f"<script type=\"application/ld+json\">{ld_json}</script>\n</head>\n<body>\n<main>\n"
        f"<p class=\"meta\"><a href=\"{config.SITE_URL}/rss.xml\">Tarihte Bugün</a> · {r['date']}</p>\n"
        f"<h1>{esc(r['title'])}</h1>\n{body}</main>\n</body>\n</html>\n")


def write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def write_all(root, articles, now, log=print):
    ordered = sorted(articles, key=lambda a: (a["pub"], a["id"]), reverse=True)
    if config.FEED_ITEMS <= 0 or not ordered:
        limit = len(ordered)
    else:   # günlük içerik sınırsız olduğundan en yeni günün tüm makaleleri RSS'te her zaman yer alır
        limit = max(config.FEED_ITEMS, sum(1 for a in ordered if a["date"] == ordered[0]["date"]))
    latest, contents = ordered[:limit], {}
    for r in latest:
        try:
            with open(os.path.join(root, r["content_file"]), encoding="utf-8") as f:
                contents[r["id"]] = f.read()
        except OSError:
            log(f"::warning::içerik dosyası eksik, RSS'e eklenmedi: {r['content_file']}")
    write_text(os.path.join(root, "rss.xml"), build_rss(latest, contents, f"{config.SITE_URL}/rss.xml", now))
    write_text(os.path.join(root, "feed"), build_rss(latest, contents, f"{config.SITE_URL}/feed", now))
    write_text(os.path.join(root, "sitemap.xml"), build_sitemap(ordered))
    return len(contents)

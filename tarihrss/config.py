"""Ayarlar. Hepsi ortam değişkenleriyle değiştirilebilir (GitHub Actions'ta env: ile)."""
import os

SITE_URL = os.environ.get("SITE_URL", "https://umutevicom-commits.github.io/tarih").rstrip("/")
SITE_ROOT = os.environ.get("SITE_ROOT", ".")
SITE_TITLE = "Tarihte Bugün – Dünya Tarihi"
SITE_DESC = ("Her gün dünya tarihinden önemli olaylar, doğumlar, ölümler, keşifler ve "
             "dönüm noktaları. Vikipedi kaynaklı, Türkçe, günlük güncellenen tarih akışı.")
ARTICLES_PER_DAY = int(os.environ.get("ARTICLES_PER_DAY", "3"))
FEED_ITEMS = int(os.environ.get("FEED_ITEMS", "50"))
TIMEZONE = "Europe/Istanbul"
CONTACT = os.environ.get("WIKI_CONTACT", "https://github.com/umutevicom-commits/tarih")
USER_AGENT = f"TarihteBugunRSS/1.0 ({CONTACT}; GitHub Actions)"
MAX_BODY_CHARS = int(os.environ.get("MAX_BODY_CHARS", "0"))   # 0 = sınırsız: maddenin tüm metni alınır
MIN_INTRO_CHARS = 350       # aday sayfa girişi en az bu kadar olmalı
MIN_TOTAL_CHARS = 1400      # makale için toplam ham metin alt sınırı
MAX_EVALUATED = 48          # bir çalışmada en fazla değerlendirilecek aday
DEFAULT_COVER = "assets/kapak-varsayilan.svg"

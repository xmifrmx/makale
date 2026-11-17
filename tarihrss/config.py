"""Ayarlar. Hepsi ortam değişkenleriyle değiştirilebilir (GitHub Actions'ta env: ile)."""
import os


def _int(name, default):
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


SITE_URL = (os.environ.get("SITE_URL") or "https://xmifrmx.github.io/makale").rstrip("/")
# Eski depo adresleri: önceki çalışmalardan kalan kayıt/sayfalar açılışta yeni adrese çevrilir.
LEGACY_SITE_URLS = ("https://umutevicom-commits.github.io/tarih",)
SITE_ROOT = os.environ.get("SITE_ROOT", ".")
SITE_TITLE = "Tarihte Bugün – Dünya Tarihi"
SITE_DESC = ("Her gün dünya tarihinden önemli olaylar, doğumlar, ölümler, keşifler ve "
             "dönüm noktaları. Vikipedi kaynaklı, Türkçe, günlük güncellenen tarih akışı.")
ARTICLES_PER_DAY = _int("ARTICLES_PER_DAY", 0)      # 0 = sınırsız: güne ait tüm uygun olay/doğum/ölüm
FEED_ITEMS = _int("FEED_ITEMS", 150)                 # RSS'teki en az öğe sayısı; en yeni günün tamamı her zaman girer (<=0: hepsi)
TIMEZONE = "Europe/Istanbul"
CONTACT = os.environ.get("WIKI_CONTACT") or "https://github.com/xmifrmx/makale"
USER_AGENT = f"TarihteBugunRSS/1.0 ({CONTACT}; GitHub Actions)"
MAX_BODY_CHARS = _int("MAX_BODY_CHARS", 0)           # 0 = sınırsız: maddenin tüm metni alınır
MIN_INTRO_CHARS = 350       # aday sayfa girişi en az bu kadar olmalı
MIN_TOTAL_CHARS = 1400      # makale için toplam ham metin alt sınırı
MAX_EVALUATED = _int("MAX_EVALUATED", 0)             # bir çalışmada değerlendirilecek en fazla aday (0 = hepsi)
DEFAULT_COVER = "assets/kapak-varsayilan.svg"

# --- tamamlama / yeniden deneme ---
BUILD_VERSION = 2           # makale üretim biçimi sürümü; eski sürümdeki yakın tarihli makaleler bir kez yeniden derlenir
RECHECK_DAYS = 3            # eksik (gaps) ya da eski sürüm makaleler için geriye bakış (gün)
MAX_SKIP_ATTEMPTS = 2       # uygunsuz bulunan aday en fazla bu kadar çalışmada yeniden denenir (sabah + 14:47)
MAX_ERROR_ATTEMPTS = 4      # API hatası alan aday en fazla bu kadar çalışmada yeniden denenir
KEEP_DAY_STATE = 14         # data/index.json içindeki günlük aday durumları kaç gün saklanır
SITEMAP_MAX = 50000         # sitemap protokol sınırı

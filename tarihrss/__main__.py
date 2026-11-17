import argparse
import sys
from datetime import date

from . import config, pipeline


def main():
    ap = argparse.ArgumentParser(description="Günlük Tarihte Bugün RSS üretici")
    ap.add_argument("--date", help="YYYY-MM-DD (varsayılan: Türkiye saatiyle bugün)")
    ap.add_argument("--count", type=int, help="günlük makale üst sınırı (boş/0 = sınırsız: güne ait tüm uygun içerik)")
    ap.add_argument("--root", default=config.SITE_ROOT)
    a = ap.parse_args()
    day = date.fromisoformat(a.date) if a.date else None
    res = pipeline.run(root=a.root, today=day, per_day=a.count)
    print(f"Bitti: yeni={res['new']} tamamlanan={res['updated']} bugün_toplam={res['today_total']} "
          f"bekleyen={res['pending']} rss_öğe={res['in_feed']}")
    if res["today_total"] == 0:
        print("::error::Bugün için hiç makale üretilemedi: " + "; ".join(res["errors"] or ["uygun aday yok"]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

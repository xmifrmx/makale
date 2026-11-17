"""Günlük üretim akışı: aday topla -> seç -> makale üret -> kaydet -> RSS/sitemap yaz."""
from __future__ import annotations
import os
from datetime import date, datetime, timedelta, timezone

from . import article, config, feed, sources, store, wiki


def local_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(config.TIMEZONE)).date()
    except Exception:
        return (datetime.now(timezone.utc) + timedelta(hours=3)).date()


def run(root=None, today=None, per_day=None, api=None, now=None, log=print):
    root = root or config.SITE_ROOT
    api = api or wiki.Api()
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    today = today or local_today()
    per_day = per_day or config.ARTICLES_PER_DAY

    data = store.load(root, log)
    arts = data["articles"]
    have = sum(1 for a in arts if a.get("date") == today.isoformat())
    need = per_day - have
    new, errors = [], []
    log(f"Tarih: {today} | bugün mevcut: {have} | hedef: {per_day}")

    if need > 0:
        used = {a["topic_key"] for a in arts}
        evs = []
        try:
            pool = sources.build_pool(api, today.month, today.day, log)
            if pool:
                evs = sources.select_candidates(api, pool, used, need, today, log)
            else:
                errors.append("aday havuzu boş (gün sayfaları alınamadı)")
        except wiki.WikiError as e:
            errors.append(str(e))
            log(f"::warning::aday seçimi başarısız: {e}")
        for ev in evs:
            if len(new) >= need:
                break
            try:
                built = article.build_article(api, ev, today, now + timedelta(seconds=len(new)), log)
            except wiki.WikiError as e:
                log(f"::warning::makale üretilemedi ({ev['title']}): {e}")
                errors.append(str(e))
                continue
            if not built:
                continue
            rec, body = built
            if rec["topic_key"] in used:
                continue
            feed.write_text(os.path.join(root, rec["content_file"]), body)
            feed.write_text(os.path.join(root, "makale", rec["slug"] + ".html"), feed.build_page(rec, body))
            arts.append(rec)
            used.add(rec["topic_key"])
            new.append(rec)
            store.save(root, data)                      # her makaleden sonra kalıcılaştır
            log(f"+ {rec['title']}  [{len(rec['title'])} kr]")

    in_feed = feed.write_all(root, arts, now, log)      # arıza olsa da RSS yeniden yazılır
    store.save(root, data)
    return {"new": len(new), "today_total": have + len(new), "errors": errors, "in_feed": in_feed}

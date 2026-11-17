"""Günlük üretim akışı: aday topla -> mevcut makaleleri denetle/tamamla -> eksik adayları ekle -> kaydet -> RSS/sitemap yaz.

Her çalışma (06:17 ana, 14:47 ikinci, elle) AYNI algoritmayı çalıştırır; bu yüzden ikinci çalışma doğal olarak
"sabah alınanları kontrol edip yalnızca eksikleri ekler":

* Güne ait TÜM uygun olay/doğum/ölüm adayları işlenir (sayı sınırı yok; ARTICLES_PER_DAY=0).
* Yayımlanmış konu (topic_key) ve olay kimliği bir daha asla eklenmez.
* Sabah API hatası yüzünden alınamayan adaylar 'error' durumunda tutulur ve sonraki çalışmada yeniden denenir.
* Sabah eksik üretilen makaleler (gaps) ya da Vikipedi'de sonradan değişen maddeler (revizyon farkı), aynı
  makale kimliği/adresiyle TEK PARÇA olarak baştan derlenir; RSS'te parça parça değil bütün makale yer alır.
"""
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


def _mark(state, cid, status):
    n = (state.get(cid) or {}).get("n", 0) + 1
    state[cid] = {"s": status, "n": n}


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _write_article(root, rec, body):
    feed.write_text(os.path.join(root, rec["content_file"]), body)
    feed.write_text(os.path.join(root, "makale", rec["slug"] + ".html"), feed.build_page(rec, body))


# ---------- eski adres / eksik sayfa onarımı ----------
def migrate(root, arts, log=print):
    """Önceki çalışmalardan kalan kayıtları geçerli SITE_URL'ye çevirir ve eksik makale sayfalarını yeniden yazar."""
    fixed = 0
    new_cover = f"{config.SITE_URL}/{config.DEFAULT_COVER}"
    for r in arts:
        old_link = r.get("link", "")
        suffix = f"/makale/{r['slug']}.html"
        old_base = old_link[:-len(suffix)] if old_link.endswith(suffix) else ""
        link = article.page_link(r["slug"])
        fallback = bool((r.get("image") or {}).get("fallback"))
        stale = old_link != link or (fallback and r["image"].get("url") != new_cover)
        page_path = os.path.join(root, "makale", r["slug"] + ".html")
        if not stale and os.path.exists(page_path):
            continue
        body = _read(os.path.join(root, r["content_file"]))
        if body is None:
            continue
        r["link"] = link
        if fallback:
            r["image"]["url"] = new_cover
        for base in {b for b in (old_base, *config.LEGACY_SITE_URLS) if b and b != config.SITE_URL}:
            body = body.replace(base, config.SITE_URL)
        _write_article(root, r, body)
        fixed += 1
    if fixed:
        log(f"{fixed} kayıt/sayfa geçerli adrese ({config.SITE_URL}) göç ettirildi")
    return fixed


# ---------- mevcut makaleleri denetle ve tamamla ----------
def _event_for(api, rec, pool_by_id):
    """Kayıttan yeniden derleme için `ev` sözlüğünü kurar (kayıtlı aday ya da güncel gün havuzu)."""
    cand = (rec.get("src") or {}).get("cand") or pool_by_id.get(rec.get("event_id"))
    if not cand:
        return None
    title = rec["topic_title"]
    info = wiki.intro_info(api, "tr", [title]).get(title)
    if not info or "disambiguation" in (info.get("pageprops") or {}):
        return None
    ev = {"title": info["title"], "info": info, "image": sources.image_from_page(info),
          "event_like": sources.event_like_title(info["title"]), "score": 0}
    return sources.enrich(ev, cand)


def refresh_existing(api, root, arts, pool, today, now, log, errors):
    """Bugünün (ve yakın günlerin eksik/eski sürüm) makalelerini denetler; gerekenleri TEK PARÇA yeniden derler."""
    iso = today.isoformat()
    floor = (today - timedelta(days=config.RECHECK_DAYS)).isoformat()
    check = [r for r in arts if r.get("date") == iso or
             (floor <= r.get("date", "") < iso and (r.get("gaps") or r.get("v", 0) < config.BUILD_VERSION))]
    if not check:
        return 0
    try:
        revs = wiki.revisions(api, "tr", [r["topic_title"] for r in check])
    except wiki.WikiError as e:
        revs = {}
        log(f"::warning::revizyon denetimi yapılamadı: {e}")

    def stale(r):
        cur = revs.get(r["topic_title"])
        return bool(r.get("gaps") or r.get("v", 0) < config.BUILD_VERSION or (cur and r.get("rev") and cur != r["rev"]))

    todo = [r for r in check if stale(r)]
    log(f"denetlenen makale: {len(check)} | tamamlanacak/yenilenecek: {len(todo)}")
    pool_by_id = {c["id"]: c for c in pool}
    done, streak = 0, 0
    for r in todo:
        try:
            ev = _event_for(api, r, pool_by_id)
            if not ev:
                log(f"::warning::yeniden derleme için kaynak bulunamadı: {r['topic_title']}")
                continue
            built = article.build_article(api, ev, date.fromisoformat(r["date"]), feed._dt(r["pub"]), log, keep=r)
            streak = 0
        except wiki.WikiError as e:
            log(f"::warning::makale tamamlanamadı ({r['topic_title']}): {e}")
            errors.append(str(e))
            streak += 1
            if streak >= 5:
                log("::warning::ardışık API hatası: tamamlama durduruldu, sonraki çalışmada sürdürülecek")
                break
            continue
        if not built:
            continue
        rec, body = built
        old_gaps = r.get("gaps") or []
        if "metin" in rec["gaps"] or (r.get("v", 0) >= config.BUILD_VERSION and len(rec["gaps"]) > len(old_gaps)):
            log(f"  eski içerik korundu (yeni derleme daha eksik): {r['topic_title']}")
            continue
        old_body = _read(os.path.join(root, r["content_file"]))
        if old_body != body:
            rec["updated"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif r.get("updated"):
            rec["updated"] = r["updated"]
        _write_article(root, rec, body)
        r.clear()
        r.update(rec)
        done += 1
        log(f"~ tamamlandı: {rec['title']}  (eksik: {rec['gaps'] or 'yok'})")
    return done


# ---------- ana akış ----------
def run(root=None, today=None, per_day=None, api=None, now=None, log=print):
    root = root or config.SITE_ROOT
    api = api or wiki.Api()
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    today = today or local_today()
    per_day = per_day or config.ARTICLES_PER_DAY            # 0 / boş = sınırsız
    iso = today.isoformat()

    data = store.load(root, log)
    arts = data["articles"]
    state = data["days"].setdefault(iso, {})
    migrate(root, arts, log)
    have = sum(1 for a in arts if a.get("date") == iso)
    new, errors = [], []
    log(f"Tarih: {today} | bugün mevcut: {have} | hedef: {per_day or 'sınırsız'}")

    failed = []
    pool = sources.build_pool(api, today.month, today.day, log, failed)
    if failed:
        errors.append("gün sayfası alınamadı: " + ", ".join(failed))
    if not pool:
        errors.append("aday havuzu boş" + (" (gün sayfaları alınamadı)" if failed else ""))

    # 1) sabah alınan içerikleri denetle; eksik/eskimiş olanları aynı makale içinde tamamla
    updated = refresh_existing(api, root, arts, pool, today, now, log, errors)

    # 2) yalnızca eksik (henüz işlenmemiş / hata almış) adayları ekle
    cap = None if per_day <= 0 else max(0, per_day - have)
    if pool and len(failed) < 2 and cap != 0:
        used = {a["topic_key"] for a in arts}
        published = {a["event_id"] for a in arts if a.get("date") == iso}
        viable, status, errs = sources.select_candidates(api, pool, used, state, published, today, log,
                                                         config.MAX_EVALUATED)
        errors += errs
        for cid, st in status.items():
            _mark(state, cid, st)
        taken = {a["slug"] for a in arts}
        first_save, streak = True, 0
        for ev in viable:
            if cap is not None and len(new) >= cap:
                break
            cid = ev["cand"]["id"]
            try:
                built = article.build_article(api, ev, today, now + timedelta(seconds=len(new)), log)
            except wiki.WikiError as e:
                log(f"::warning::makale üretilemedi ({ev['title']}): {e}")
                errors.append(str(e))
                _mark(state, cid, "error")
                streak += 1
                if streak >= 5:
                    log("::warning::ardışık API hatası: üretim durduruldu, kalanlar sonraki çalışmada işlenecek")
                    break
                continue
            streak = 0
            if not built:
                _mark(state, cid, "skip")
                continue
            rec, body = built
            if rec["topic_key"] in used:
                _mark(state, cid, "dup")
                continue
            article.unique_slug(rec, taken)
            _write_article(root, rec, body)
            arts.append(rec)
            used.add(rec["topic_key"])
            taken.add(rec["slug"])
            state[cid] = {"s": "published", "n": 1}
            new.append(rec)
            store.save(root, data, backup=first_save)            # her makaleden sonra kalıcılaştır
            first_save = False
            log(f"+ {rec['title']}  [{len(rec['title'])} kr]" + (f"  eksik={rec['gaps']}" if rec["gaps"] else ""))

    pending = sum(1 for v in state.values() if v.get("s") == "error")
    if pending:
        log(f"::warning::{pending} aday API hatası nedeniyle işlenemedi; sonraki çalışmada (14:47) tamamlanacak")
    store.prune_days(data, iso, config.KEEP_DAY_STATE)
    in_feed = feed.write_all(root, arts, now, log)          # arıza olsa da RSS yeniden yazılır
    store.save(root, data)
    return {"new": len(new), "updated": updated, "today_total": have + len(new), "errors": errors,
            "in_feed": in_feed, "pending": pending}

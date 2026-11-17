"""Kalıcı kayıt: data/index.json (+ .bak yedeği). Bozulmaya karşı korumalı, atomik yazım."""
from __future__ import annotations
import json
import os
import shutil


class StoreError(RuntimeError):
    pass


def _path(root):
    return os.path.join(root, "data", "index.json")


def _read(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not (isinstance(data, dict) and isinstance(data.get("articles"), list)):
        raise ValueError("beklenmeyen biçim")
    return data


def load(root, log=print):
    p = _path(root)
    for cand in (p, p + ".bak"):
        if os.path.exists(cand):
            try:
                data = _read(cand)
                if cand != p:
                    log("::warning::index.json okunamadı, .bak yedeğinden devam ediliyor")
                if not isinstance(data.get("days"), dict):
                    data["days"] = {}          # günlük aday durumları (eski kayıtlarda yoktur)
                return data
            except (OSError, ValueError):
                continue
    if os.path.exists(p) or os.path.exists(p + ".bak"):
        raise StoreError("data/index.json bozuk ve yedek okunamadı; git geçmişinden geri yükleyin")
    return {"version": 2, "articles": [], "days": {}}


def prune_days(data, today_iso, keep_days):
    """Eski günlerin aday durumlarını siler (index.json şişmesin)."""
    from datetime import date, timedelta
    floor = (date.fromisoformat(today_iso) - timedelta(days=keep_days)).isoformat()
    data["days"] = {d: v for d, v in data.get("days", {}).items() if d >= floor}


def save(root, data, backup=True):
    """backup=False: .bak yedeği yenilenmez (bir çalışmada çok sayıda ara kayıtta gereksiz kopyayı önler)."""
    p = _path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if backup and os.path.exists(p):
        try:
            _read(p)
            shutil.copyfile(p, p + ".bak")      # yalnızca sağlam dosya yedeklenir
        except (OSError, ValueError):
            pass
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)

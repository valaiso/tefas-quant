#!/usr/bin/env python3
"""Günlük derlemenin gerekip gerekmediğine saniyeler içinde karar verir.

TEFAS bir işlem gününün fiyatlarını o gün sabah (09:00-09:30 TR) yayımlar;
akşam çalışan derleme o günün kapanış verisiyle siteyi bir kez üretir.
GitHub zamanlanmış işleri gecikebildiği ya da atlanabildiği için iş akışında
iki akşam denemesi var; bu betik ikinci denemenin gereksiz derleme yapmasını
önler:

  1. Hafta sonu mu?                          -> derleme yok
  2. Yayındaki site zaten bugünün fiyatında mı? -> derleme yok
  3. TEFAS bugünün fiyatını yayımlamış mı?   -> yoksa (tatil) derleme yok

Sonuç GitHub Actions'a `run=true|false` olarak yazılır.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quant.tefas import Tefas  # noqa: E402

TR = ZoneInfo("Europe/Istanbul")


def published_last_date(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "tefas-quant/ci"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")).get("lastDataDate")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        print(f"Yayındaki meta.json okunamadı ({exc}); güncel değil sayılıyor")
        return None


def tefas_has(day: dt.date) -> bool:
    client = Tefas(delay=1.0, max_retry=3, verbose=False)
    return any(True for _ in client.prices("YAT", day, day))


def emit(run: bool, reason: str) -> int:
    print(f"{'DERLE' if run else 'ATLA'}: {reason}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if run else 'false'}\nreason={reason}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL", ""))
    args = parser.parse_args()

    now = dt.datetime.now(TR)
    today = now.date()
    print(f"Türkiye saati: {now:%Y-%m-%d %H:%M}")
    if today.weekday() >= 5:
        return emit(False, "hafta sonu, TEFAS fiyat yayımlamıyor")

    last = published_last_date(args.site_url.rstrip("/") + "/data/meta.json") if args.site_url else None
    print(f"Yayındaki son fiyat günü: {last or 'bilinmiyor'}")
    if last and last >= today.isoformat():
        return emit(False, f"site zaten {last} fiyatını gösteriyor")

    if not tefas_has(today):
        return emit(False, f"TEFAS {today} için fiyat yayımlamamış (tatil)")
    return emit(True, f"{today} kapanış verisiyle site güncellenecek")


if __name__ == "__main__":
    raise SystemExit(main())

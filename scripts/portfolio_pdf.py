"""Kişisel Portföy Raporu PDF'i (aylık e-posta için, yalnızca CI'da).

    python scripts/portfolio_pdf.py --site-url https://valaiso.github.io/tefas-quant --out portfoy-rapor.pdf

Portföy Analiz'in Supabase'indeki portfolio_state satırından okunur ve yayındaki sitenin
#/portfoyrapor sayfasına tarayıcıda (window.__TQ_PORTFOLIO__) verilir; hiçbir dosyaya ya da
siteye yazılmaz, yalnızca PDF'e basılır. Günlüğe pozisyon bilgisi yazdırılmaz.

Ortam değişkenleri (GitHub Actions secret):
    SUPABASE_SERVICE_ROLE_KEY  Analiz Supabase projesinin service role anahtarı
    PORTFOLIO_USER_ID          (isteğe bağlı) portföy sahibinin kullanıcı kimliği; yoksa en son güncellenen satır
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

SUPABASE_URL = "https://jqmfvinbzgqyitqquzdc.supabase.co"


def read_state() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not key:
        raise SystemExit("SUPABASE_SERVICE_ROLE_KEY tanımlı değil; portföy raporu atlandı")
    q = {"select": "state_json,updated_at", "order": "updated_at.desc", "limit": "1"}
    uid = os.environ.get("PORTFOLIO_USER_ID", "").strip()
    if uid:
        q["user_id"] = f"eq.{uid}"
    req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/portfolio_state?{urllib.parse.urlencode(q)}",
                                 headers={"apikey": key, "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.loads(r.read().decode("utf-8"))
    if not rows or not rows[0].get("state_json"):
        raise SystemExit("portfolio_state satırı bulunamadı")
    state = rows[0]["state_json"]
    snaps = {k: v for k, v in (state.get("monthlySnapshots") or {}).items() if (v or {}).get("rows")}
    if not snaps:
        raise SystemExit("Hesapta aylık pozisyon fotoğrafı yok (Analiz Panel'i bir kez açılmalı)")
    last = max(snaps)
    # Rapor için gereken en az veri: son aylık fotoğraf
    return {"monthlySnapshots": {last: snaps[last]}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site-url", required=True)
    ap.add_argument("--out", default="portfoy-rapor.pdf")
    ap.add_argument("--state-file", help="yerel deneme: Supabase yerine bu JSON (monthlySnapshots içeren durum)")
    ap.add_argument("--channel", help="yerel deneme: kurulu tarayıcı (ör. msedge)")
    args = ap.parse_args()
    slim = json.load(open(args.state_file, encoding="utf-8")) if args.state_file else read_state()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel) if args.channel else p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1600})
        page.add_init_script(f"window.__TQ_PORTFOLIO__ = {json.dumps(slim, ensure_ascii=False)};")
        page.goto(f"{args.site_url.rstrip('/')}/?t={os.getpid()}#/portfoyrapor", wait_until="networkidle", timeout=90_000)
        page.wait_for_function("window.__TQ_READY__ === true && document.querySelectorAll('.rp-page').length > 0", timeout=90_000)
        page.wait_for_timeout(1500)
        page.emulate_media(media="print")
        page.pdf(path=args.out, format="A4", print_background=True, prefer_css_page_size=True,
                 margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        n = page.evaluate("document.querySelectorAll('.rp-page').length")
        browser.close()
    print(f"Portföy raporu basıldı: {n} sayfa → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

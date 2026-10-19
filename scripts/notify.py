"""Aylık rapor bildirimleri (ntfy): telefona kısa, resmi bildirim.

    python scripts/notify.py --slot sabah|aksam [--now] [--force rapor|hatirlatma]

Ayın 1'i 09:00   "Bugün raporlarınız gönderilecek"
Ayın 1'i 18:00   "Raporlarınız gönderildi" (o günkü e-posta işi başarısızsa sorun bildirilir)
Ayın son günü 09:00 ve 18:00   "Yarın raporlarınız gönderilecek" hatırlatması
Başka günlerde hiçbir şey göndermez. GitHub zamanlanmış işleri geciktirebildiği için iş birkaç dakika
erken başlatılır; betik hedef saate (İstanbul) kadar bekler.

Ortam değişkenleri (GitHub Actions secret / değişkenleri):
    NTFY_TOPIC    ntfy kanal adı (gizli tutulur; telefondaki ntfy uygulaması bu kanala abone olur)
    SITE_URL      bildirime dokununca açılacak site
    GITHUB_TOKEN, GITHUB_REPOSITORY   akşam bildiriminde e-posta işinin sonucunu okumak için (isteğe bağlı)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request

TR = dt.timezone(dt.timedelta(hours=3))
TARGET_HOUR = {"sabah": 9, "aksam": 18}
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def _mail_ok(today: dt.date) -> bool | None:
    """Bugün çalışan son 'Aylık Model Rapor e-postası' işinin sonucu; okunamazsa None."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/workflows/monthly-report.yml/runs?per_page=5",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    try:
        runs = json.load(urllib.request.urlopen(req, timeout=20)).get("workflow_runs", [])
    except Exception as e:  # noqa: BLE001 - bildirim yine gider
        print(f"e-posta işi okunamadı: {e}")
        return None
    for r in runs:
        started = dt.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).astimezone(TR).date()
        if started == today and r.get("status") == "completed":
            return r.get("conclusion") == "success"
    return None


def message(kind: str, slot: str, today: dt.date) -> tuple[str, str, list[str]]:
    if kind == "hatirlatma":
        nxt = today + dt.timedelta(days=1)
        return ("Hatırlatma: Raporlarınız yarın gönderilecek",
                f"{MONTHS[today.month - 1]} ayına ait Portföy ve Model Performans raporlarınız yarın "
                f"({nxt.day} {MONTHS[nxt.month - 1]}) saat 18:00'e kadar e-posta adresinize gönderilecektir.",
                ["bell"])
    month = MONTHS[(today.month - 2) % 12]
    if slot == "sabah":
        return ("Bugün raporlarınız gönderilecek",
                f"{month} ayına ait Portföy ve Model Performans raporlarınız bugün saat 18:00'e kadar "
                "e-posta adresinize gönderilecektir.", ["calendar"])
    ok = _mail_ok(today)
    if ok is False:
        return ("Rapor gönderiminde sorun oluştu",
                f"{month} ayına ait raporlarınız e-postayla gönderilemedi. Raporları sitede inceleyebilirsiniz; "
                "gönderim kaydı GitHub Actions üzerinde kontrol edilmelidir.", ["warning"])
    return ("Raporlarınız gönderildi",
            f"{month} ayına ait Portföy ve Model Performans raporlarınız e-posta adresinize gönderilmiştir.",
            ["white_check_mark"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", choices=TARGET_HOUR, required=True)
    ap.add_argument("--now", action="store_true", help="hedef saati bekleme")
    ap.add_argument("--force", choices=["rapor", "hatirlatma"], help="tarih kontrolünü atla (deneme)")
    a = ap.parse_args()

    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("NTFY_TOPIC tanımlı değil; bildirim gönderilmedi.")
        return 0
    now = dt.datetime.now(TR)
    today = now.date()
    kind = a.force or ("rapor" if today.day == 1 else "hatirlatma" if (today + dt.timedelta(days=1)).day == 1 else None)
    if not kind:
        print(f"{today}: bildirim günü değil.")
        return 0

    target = now.replace(hour=TARGET_HOUR[a.slot], minute=0, second=0, microsecond=0)
    wait = (target - now).total_seconds()
    if not a.now and 0 < wait <= 30 * 60:
        print(f"{target:%H:%M}'e {wait / 60:.1f} dk bekleniyor")
        time.sleep(wait)

    title, body, tags = message(kind, a.slot, today)
    site = (os.environ.get("SITE_URL") or "https://valaiso.github.io/tefas-quant/").rstrip("/") + "/"
    # iPhone'da uygulama ikonu değiştirilemez; logo ek olarak gider ve bildirimde küçük görsel olarak görünür
    payload = {"topic": topic, "title": title, "message": body, "tags": tags, "priority": 4, "click": site,
               "icon": site + "assets/img/logo-192.png", "attach": site + "assets/img/logo-192.png", "filename": "tefas-quant.png"}
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"gönderildi ({r.status}): {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

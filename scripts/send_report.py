"""Aylık Model Rapor e-postası: resmi yazı + PDF eki + siteye bağlantı.

    python scripts/send_report.py --site-url https://valaiso.github.io/tefas-quant --pdf model-rapor.pdf \
        [--portfolio-pdf portfoy-rapor.pdf]

Gönderim bilgileri ortam değişkenlerinden (GitHub Actions secret) okunur, depoda tutulmaz:
    MAIL_USER          gönderen Gmail adresi
    MAIL_APP_PASSWORD  o hesabın Gmail uygulama şifresi
    MAIL_TO            alıcı adres(ler)i, virgülle ayrılmış
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import smtplib
import ssl
import sys
import urllib.request
from email.message import EmailMessage
from pathlib import Path

MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def _today_tr() -> dt.date:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)).date()


def _last_full(dates: list[str]) -> int:
    """Son tamamlanmış ayın bitiş noktası (rapor sayfasıyla aynı kural)."""
    n = len(dates) - 1
    prev, cur = dates[n - 1][:7], dates[n][:7]
    if (cur != prev and int(dates[n][8:10]) <= 4) or cur < _today_tr().isoformat()[:7]:
        return n
    return n - 1


def _ok_pdf(path: str | None) -> bool:
    return bool(path) and Path(path).exists() and Path(path).stat().st_size > 10_000


def _letter(rep: dict, site_url: str, with_portfolio: bool = False) -> tuple[str, str, str]:
    """Resmi yazı: konu etiketi, HTML gövde ve düz metin gövde (tablo yok; ayrıntılar PDF ekinde)."""
    models = rep["models"]
    ref = next((m for m in models if m["kind"] == "fon"), models[0])
    e = _last_full(ref["dates"])
    month = ref["dates"][e - 1]
    label = f"{MONTHS[int(month[5:7]) - 1]} {month[:4]}"
    today = _today_tr()
    date_txt = f"{today.day} {MONTHS[today.month - 1]} {today.year}"
    link = f"{site_url}/#/modelrapor"
    paras = [
        "Sayın İlgili,",
        f"TEFAS Quant model portföylerinin {label} dönemine ait aylık performans raporu ekte bilgilerinize sunulmuştur.",
        "Raporda Güvenli, Dengeli ve Atak fon modelleri ile BES Öneri modelinin aylık getirileri; para piyasası fonları "
        "ortalaması (PPF), TÜFE, gram altın, dolar/TL ve S&P 500 (TL) ile karşılaştırmalı olarak yer almaktadır. Özet "
        "bölümünde son 12 aylık dönemsel getiriler ve aylık getiri ısı haritası, model sayfalarında ise birikimli getiri, "
        "kıyaslara göre farklar ve ay ay getiri tabloları bulunmaktadır.",
        *(["Ekte ayrıca kişisel portföyünüzün aynı döneme ait raporu ayrı bir dosya olarak yer almaktadır. Analiz'in aylık "
            "portföy raporu esas alınarak hazırlanan bu raporda para giriş ve çıkışlarından arındırılmış aylık getiriniz, reel "
            "getiriniz, değer köprüsü, dağılım, pozisyonlar ve risk göstergeleri TEFAS Quant model portföyleriyle (Güvenli, "
            "Dengeli, Atak, BES Öneri) ve kıyaslarla birlikte sunulmaktadır."] if with_portfolio else []),
        "Raporun güncel hâline aşağıdaki bağlantıdan da ulaşabilirsiniz.",
        "Bilgilerinize sunar, iyi çalışmalar dileriz.",
    ]
    note = ("Model getirileri fon fiyatlarından, vergi öncesi ve geriye dönük test olarak hesaplanmıştır; geçmiş getiri "
            "gelecekteki sonuçların göstergesi değildir. Bu e-posta ve eki yatırım tavsiyesi niteliği taşımaz.")
    ek = [f"TEFAS Quant Model Performans Raporu – {label} (PDF)"]
    if with_portfolio:
        ek.append(f"TEFAS Quant Kişisel Portföy Raporu – {label} (PDF)")
    p_html = "".join(f'<p style="margin:0 0 14px;line-height:1.6">{t}</p>' for t in paras)
    html = f"""<div style="font-family:Segoe UI,Arial,sans-serif;color:#12233d;max-width:620px;font-size:14px">
  <div style="border-bottom:3px solid #1f5fbf;padding:0 0 12px;margin-bottom:18px">
    <div style="font-size:18px;font-weight:700;color:#0b2a5b">TEFAS Quant</div>
    <div style="font-size:11px;letter-spacing:.14em;color:#64748b">MODEL PORTFÖY RAPORU</div>
  </div>
  <p style="margin:0 0 4px;text-align:right;color:#475569">{date_txt}</p>
  <p style="margin:0 0 18px"><b>Konu:</b> {label} Model Performans Raporu</p>
  {p_html}
  <p style="margin:4px 0 22px"><a href="{link}" style="display:inline-block;background:#1f5fbf;color:#fff;text-decoration:none;
    font-weight:700;padding:10px 18px;border-radius:6px">Raporu sitede aç →</a></p>
  <p style="margin:0 0 2px">Saygılarımızla,</p>
  <p style="margin:0 0 22px"><b>TEFAS Quant</b></p>
  <p style="margin:0;padding-top:12px;border-top:1px solid #e3e9f2;font-size:11px;color:#64748b;line-height:1.5">
    <b>Ekler:</b> {"<br>".join(f"{i + 1}. {e}" for i, e in enumerate(ek))}<br>{note}</p>
</div>"""
    text = (f"{date_txt}\n\nKonu: {label} Model Performans Raporu\n\n" + "\n\n".join(paras)
            + f"\n\nRaporu sitede aç: {link}\n\nSaygılarımızla,\nTEFAS Quant\n\nEkler:\n" + "\n".join(f"{i + 1}. {e}" for i, e in enumerate(ek)) + f"\n{note}\n")
    return label, html, text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site-url", required=True)
    ap.add_argument("--pdf", default=None, help="Model Rapor PDF'i")
    ap.add_argument("--portfolio-pdf", default=None, help="Kişisel Portföy Raporu PDF'i (yoksa yalnızca model raporu gider)")
    ap.add_argument("--dry-run", action="store_true", help="göndermeden HTML'i yazdır")
    args = ap.parse_args()
    site = args.site_url.rstrip("/")

    with urllib.request.urlopen(f"{site}/data/model_report.json?t={dt.datetime.now().timestamp():.0f}", timeout=60) as r:
        rep = json.loads(r.read().decode("utf-8"))
    if not rep.get("models"):
        print("model_report.json boş; e-posta gönderilmedi", file=sys.stderr)
        return 1
    label, html, text = _letter(rep, site, with_portfolio=_ok_pdf(args.portfolio_pdf))
    if args.dry_run:
        print(html)
        return 0

    user = os.environ.get("MAIL_USER", "").strip()
    pw = os.environ.get("MAIL_APP_PASSWORD", "").replace(" ", "").strip()
    to = [a.strip() for a in os.environ.get("MAIL_TO", "").split(",") if a.strip()]
    if not (user and pw and to):
        print("MAIL_USER, MAIL_APP_PASSWORD ve MAIL_TO secret'ları tanımlı olmalı", file=sys.stderr)
        return 1

    msg = EmailMessage()
    msg["Subject"] = f"TEFAS Quant | {label} Model Performans Raporu"
    msg["From"] = f"TEFAS Quant <{user}>"
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    tag = label.replace(" ", "-")
    for path, name in ((args.pdf, f"TEFAS-Quant-Model-Raporu-{tag}.pdf"), (args.portfolio_pdf, f"TEFAS-Quant-Portfoy-Raporu-{tag}.pdf")):
        if _ok_pdf(path):
            msg.add_attachment(Path(path).read_bytes(), maintype="application", subtype="pdf", filename=name)
        elif path:
            print(f"{path} bulunamadı; bu ek gönderilmiyor", file=sys.stderr)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=60) as s:
        s.login(user, pw)
        s.send_message(msg)
    print(f"Gönderildi: {label} → {len(to)} alıcı")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Aylık Model Rapor e-postası: yayındaki siteden özet tablo + PDF eki.

    python scripts/send_report.py --site-url https://valaiso.github.io/tefas-quant --pdf model-rapor.pdf

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
BENCH = [("ppf", "PPF ortalaması"), ("tufe", "TÜFE"), ("gold", "Gram altın"), ("usd", "Dolar/TL"), ("sp500", "S&P 500 (TL)")]


def _today_tr() -> dt.date:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)).date()


def _last_full(dates: list[str]) -> int:
    """Son tamamlanmış ayın bitiş noktası (rapor sayfasıyla aynı kural)."""
    n = len(dates) - 1
    prev, cur = dates[n - 1][:7], dates[n][:7]
    if (cur != prev and int(dates[n][8:10]) <= 4) or cur < _today_tr().isoformat()[:7]:
        return n
    return n - 1


def _ret(s: list, i0: int, i1: int) -> float | None:
    if i0 < 0 or s[i0] is None or s[i1] is None:
        return None
    return (s[i1] / s[i0] - 1) * 100


def _pct(v: float | None) -> str:
    if v is None:
        return "—"
    sign = "+" if v > 0 else "−" if v < 0 else ""
    return f"{sign}%{abs(v):.1f}".replace(".", ",")


def _cell(v: float | None, bold: bool = False) -> str:
    color = "#0f8a50" if (v or 0) > 0 else "#d6404a" if (v or 0) < 0 else "#475569"
    txt = f"<b>{_pct(v)}</b>" if bold else _pct(v)
    return f'<td style="padding:6px 10px;text-align:right;color:{color};border-bottom:1px solid #e3e9f2">{txt}</td>'


def build_html(rep: dict, site_url: str) -> tuple[str, str]:
    models = rep["models"]
    ref = next((m for m in models if m["kind"] == "fon"), models[0])
    e = _last_full(ref["dates"])
    month = ref["dates"][e - 1]
    label = f"{MONTHS[int(month[5:7]) - 1]} {month[:4]}"

    def row(name: str, dates: list[str], s: list, self_row: bool) -> str:
        eM = _last_full(dates)
        bg = "#ffffff" if self_row else "#f8fafd"
        return (f'<tr style="background:{bg}"><td style="padding:6px 10px;border-bottom:1px solid #e3e9f2">'
                f'{"<b>" + name + "</b>" if self_row else name}</td>'
                f"{_cell(_ret(s, eM - 1, eM), self_row)}{_cell(_ret(s, eM - 3, eM))}{_cell(_ret(s, eM - 12, eM))}</tr>")

    rows = [row(m["label"], m["dates"], m["series"]["model"], True) for m in models]
    rows += [row(lbl, ref["dates"], ref["series"][k], False) for k, lbl in BENCH if k in ref["series"]]
    th = 'style="padding:7px 10px;text-align:right;font-size:11px;letter-spacing:.05em;background:#0b2a5b;color:#fff"'
    html = f"""<div style="font-family:Segoe UI,Arial,sans-serif;color:#12233d;max-width:640px">
  <div style="background:linear-gradient(120deg,#0b2a5b,#1f5fbf);color:#fff;padding:20px 24px;border-radius:10px 10px 0 0">
    <div style="font-size:12px;letter-spacing:.14em;opacity:.8">TEFAS QUANT · AYLIK RAPOR</div>
    <div style="font-size:22px;font-weight:700;margin-top:6px">Model Performans Raporu · {label}</div>
  </div>
  <div style="padding:16px 4px">
    <p style="margin:0 0 12px">{label} sonu itibarıyla fon modelleri (Güvenli, Dengeli, Atak) ve BES Öneri'nin getirileri,
      PPF, TÜFE, altın, dolar ve S&amp;P 500 ile karşılaştırmalı. Ayrıntılı rapor ekteki PDF'te.</p>
    <table style="border-collapse:collapse;width:100%;font-size:13px">
      <thead><tr><th style="padding:7px 10px;text-align:left;font-size:11px;letter-spacing:.05em;background:#0b2a5b;color:#fff">MODEL / KIYAS</th>
        <th {th}>{MONTHS[int(month[5:7]) - 1].upper()}</th><th {th}>3 AY</th><th {th}>12 AY</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    <p style="margin:16px 0 0"><a href="{site_url}/#/modelrapor" style="color:#1f5fbf;font-weight:700">Raporu sitede aç →</a></p>
    <p style="margin:14px 0 0;font-size:11px;color:#64748b">Getiriler vergi öncesi, geriye dönük testtir; geçmiş getiri geleceği göstermez. Yatırım tavsiyesi değildir.</p>
  </div>
</div>"""
    return label, html


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site-url", required=True)
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--dry-run", action="store_true", help="göndermeden HTML'i yazdır")
    args = ap.parse_args()
    site = args.site_url.rstrip("/")

    with urllib.request.urlopen(f"{site}/data/model_report.json?t={dt.datetime.now().timestamp():.0f}", timeout=60) as r:
        rep = json.loads(r.read().decode("utf-8"))
    if not rep.get("models"):
        print("model_report.json boş; e-posta gönderilmedi", file=sys.stderr)
        return 1
    label, html = build_html(rep, site)
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
    msg["Subject"] = f"TEFAS Quant · Model Raporu · {label}"
    msg["From"] = f"TEFAS Quant <{user}>"
    msg["To"] = ", ".join(to)
    msg.set_content(f"TEFAS Quant Model Performans Raporu ({label}). Rapor: {site}/#/modelrapor")
    msg.add_alternative(html, subtype="html")
    if args.pdf and Path(args.pdf).exists() and Path(args.pdf).stat().st_size > 10_000:
        msg.add_attachment(Path(args.pdf).read_bytes(), maintype="application", subtype="pdf",
                           filename=f"TEFAS-Quant-Model-Raporu-{label.replace(' ', '-')}.pdf")
    else:
        print("PDF bulunamadı; e-posta eksiz gönderiliyor", file=sys.stderr)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=60) as s:
        s.login(user, pw)
        s.send_message(msg)
    print(f"Gönderildi: {label} → {len(to)} alıcı")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

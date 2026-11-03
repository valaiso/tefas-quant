"""Üretilen site verisinin denetimi (yayından önce).

    python scripts/validate_site.py [--out dist] [--max-age-days 6]

Hata (errors): yayın durdurulur (çıkış kodu 1), eski site yerinde kalır.
Uyarı (warnings): yayın sürer; sitedeki ↻ düğmesi ve dist/data/checks.json gösterir.
Denetimler: dosyalar okunuyor mu, NaN / Infinity / boş alan, skor 0–100, not / sinyal geçerli mi, fon kodları tekil mi,
son fiyat günü taze mi, olağan dışı günlük getiri, fon sayısı makul mü, model sepetlerinde ağırlık toplamı 100 mü,
sepetteki fonlar sıralamada var mı, günlük ve aylık seriler sıralı mı.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

GRADES = {"A+", "A", "B", "C", "D"}
SIGNALS = {"GÜÇLÜ AL", "AL", "İZLE", "ZAYIF", "UZAK DUR"}


def _bad_numbers(obj, path="", out=None, limit=20):
    """JSON içinde NaN / Infinity (json.load bunları float olarak okur)."""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(obj, float) and not math.isfinite(obj):
        out.append(path)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _bad_numbers(v, f"{path}.{k}", out, limit)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5000]):
            _bad_numbers(v, f"{path}[{i}]", out, limit)
    return out


def _sorted_dates(dates) -> bool:
    return all(a < b for a, b in zip(dates, dates[1:]))


def validate(out: Path, max_age_days: int = 6) -> dict:
    data = out / "data"
    errors, warnings = [], []
    files = {}
    for name in ["meta", "funds", "categories", "backtest", "benchmarks", "simulation", "model", "model_report", "bes", "bes_model"]:
        p = data / f"{name}.json"
        if not p.exists():
            (errors if name in ("meta", "funds", "categories") else warnings).append(f"{name}.json yok")
            continue
        try:
            files[name] = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}.json okunamadı: {e}")
            continue
        bad = _bad_numbers(files[name])
        if bad:
            errors.append(f"{name}.json geçersiz sayı (NaN/Infinity): {', '.join(bad[:3])}")

    meta, funds = files.get("meta"), files.get("funds")
    if meta and funds is not None:
        funds = funds["funds"] if isinstance(funds, dict) else funds
        last = dt.date.fromisoformat(meta["lastDataDate"])
        age = (dt.date.today() - last).days
        if age > max_age_days:
            warnings.append(f"son fiyat günü {last:%d.%m.%Y} ({age} gün önce); TEFAS verisi güncellenmemiş olabilir")
        if not 600 <= len(funds) <= 3000:
            errors.append(f"fon sayısı olağan dışı: {len(funds)}")
        if meta.get("fundCount") != len(funds):
            warnings.append(f"meta.fundCount ({meta.get('fundCount')}) ile fon listesi ({len(funds)}) farklı")
        codes = [f.get("c") for f in funds]
        dup = {c for c in codes if codes.count(c) > 1}
        if dup:
            errors.append(f"tekrarlanan fon kodu: {', '.join(sorted(dup)[:5])}")
        bad_score = [f["c"] for f in funds if not isinstance(f.get("s"), (int, float)) or not 0 <= f["s"] <= 100]
        if bad_score:
            errors.append(f"skoru 0–100 dışında / boş fon: {', '.join(bad_score[:5])} ({len(bad_score)})")
        bad_grade = [f["c"] for f in funds if f.get("g") not in GRADES or f.get("sig") not in SIGNALS]
        if bad_grade:
            errors.append(f"geçersiz not / sinyal: {', '.join(bad_grade[:5])}")
        no_name = [f["c"] for f in funds if not f.get("n") or not f.get("k")]
        if no_name:
            warnings.append(f"adı ya da kategorisi boş fon: {', '.join(no_name[:5])} ({len(no_name)})")
        jump = [f"{f['c']} %{f['r']['1g']:.1f}" for f in funds if abs((f.get("r") or {}).get("1g") or 0) > 25]
        if jump:
            warnings.append(f"günlük getirisi ±%25'i aşan fon (bölünme / hatalı fiyat olabilir): {', '.join(jump[:5])}")
        top = [f for f in funds if f.get("g") in ("A+", "A")]
        if not top:
            errors.append("hiç A / A+ fon yok")
        risky = [f["c"] for f in top if f.get("q") or (f.get("cap") or {}).get("young") or (f.get("cap") or {}).get("concentration")]
        if risky:
            errors.append(f"önerilmemesi gereken fon A / A+ almış: {', '.join(risky[:5])}")
        hist_dir = data / "history"
        missing = [c for c in codes[:2000] if not (hist_dir / f"{c}.json").exists()]
        if missing:
            warnings.append(f"geçmiş fiyat dosyası eksik: {', '.join(missing[:5])} ({len(missing)})")

    by = {f["c"]: f for f in (funds or [])}
    for key, label in (("model", "fon modeli"), ("bes_model", "BES modeli")):
        m = files.get(key)
        if not m:
            continue
        for pk, p in (m.get("profiles") or {}).items():
            basket = p.get("basket") or []
            if not basket:
                warnings.append(f"{label} {pk}: sepet boş")
                continue
            tot = sum(b.get("w") or 0 for b in basket)
            if abs(tot - 100) > 0.6:
                errors.append(f"{label} {pk}: ağırlık toplamı %{tot:g}")
            if key == "model":
                gone = [b["c"] for b in basket if b["c"] not in by]
                if gone:
                    warnings.append(f"{label} {pk}: sıralamada olmayan fon {', '.join(gone)}")
            bt = p.get("backtest") or {}
            if bt.get("available") and not _sorted_dates(bt.get("dates") or []):
                errors.append(f"{label} {pk}: geçmiş test tarihleri sıralı değil")

    rep = files.get("model_report")
    if rep and rep.get("daily"):
        d = rep["daily"]
        if not _sorted_dates(d.get("dates") or []):
            errors.append("model raporu günlük seri tarihleri sıralı değil")
        for k, v in (d.get("series") or {}).items():
            if len(v) != len(d["dates"]):
                errors.append(f"model raporu günlük seri uzunluğu farklı: {k}")

    return {"ok": not errors, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "lastDataDate": (meta or {}).get("lastDataDate"), "errors": errors, "warnings": warnings}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--max-age-days", type=int, default=6)
    a = ap.parse_args()
    res = validate(Path(a.out), a.max_age_days)
    (Path(a.out) / "data" / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for e in res["errors"]:
        print(f"HATA: {e}")
    for w in res["warnings"]:
        print(f"uyarı: {w}")
    print(f"[denetim] {'geçti' if res['ok'] else 'BAŞARISIZ'} · {len(res['errors'])} hata · {len(res['warnings'])} uyarı")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

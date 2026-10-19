"""Model Rapor: fon modelleri (Güvenli / Dengeli / Atak) ve BES Öneri modelinin aylık
getirilerini PPF, TÜFE, gram altın, dolar/TL ve S&P 500 (TL) ile karşılaştıran veri.

Her model kendi geriye dönük testinin aylık noktalarını kullanır (T+1 alış günleri,
yaklaşık her ayın ilk işlem günü); kıyaslar aynı günlerden ileri doldurularak alınır.
"""
from __future__ import annotations

import pandas as pd

BENCH_KEYS = ("ppf", "tufe", "gold", "usd", "sp500")


def _levels(values, dates: pd.DatetimeIndex) -> list[float | None]:
    s = pd.Series(values, index=dates, dtype=float)
    base = s.dropna()
    if base.empty:
        return [None] * len(s)
    s = s / base.iloc[0] * 100
    return [None if pd.isna(x) else round(float(x), 3) for x in s.values]


def _entry(key: str, label: str, kind: str, dates: list[str], model: list, bench: pd.DataFrame) -> dict | None:
    if len(dates) < 3:
        return None
    idx = pd.to_datetime(dates)
    series = {"model": _levels(model, idx)}
    for b in BENCH_KEYS:
        if b not in bench or bench[b].isna().all():
            continue
        s = bench[b].reindex(bench.index.union(idx)).ffill().reindex(idx)
        series[b] = _levels(s.values, idx)
    return {"key": key, "label": label, "kind": kind, "dates": dates, "series": series}


def build(mdl: dict, bes_model: dict | None, bench: pd.DataFrame) -> dict:
    models = []
    for key, p in (mdl.get("profiles") or {}).items():
        bt = p.get("backtest") or {}
        if bt.get("available"):
            e = _entry(key, p["label"], "fon", bt["dates"], bt["series"]["model"], bench)
            if e:
                models.append(e)
    bf = (bes_model or {}).get("befas") or {}
    mo = (bf.get("backtest") or {}).get("monthly")
    if mo:
        e = _entry("bes", "BES Öneri", "bes", mo["dates"], mo["model"], bench)
        if e:
            models.append(e)
    # Üç BES modeli (Koruyucu / Dengeli / Büyüme): Modellerle Karşılaştır sayfası için ayrı liste
    bes_profiles = []
    for key, p in ((bes_model or {}).get("profiles") or {}).items():
        mo = (p.get("backtest") or {}).get("monthly")
        if mo:
            e = _entry(f"bes_{key}", f"BES {p.get('label', key)}", "besprof", mo["dates"], mo["model"], bench)
            if e:
                bes_profiles.append(e)
    return {"asOf": mdl.get("asOf"), "models": models, "besProfiles": bes_profiles}

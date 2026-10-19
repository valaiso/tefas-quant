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


DAILY_MONTHS = 39  # Model Simülasyonu grafiği en fazla 3 yıl geriye bakar (+3 ay pay)


def _daily(entries: list[tuple[str, dict]], bench: pd.DataFrame) -> dict | None:
    """Modellerin ve kıyasların günlük seviyeleri ortak takvimde (ileri doldurulmuş)."""
    if not entries:
        return None
    idx = bench.index
    for _, d in entries:
        idx = idx.union(pd.to_datetime(d["dates"]))
    start = idx[-1] - pd.DateOffset(months=DAILY_MONTHS)
    idx = idx[idx >= start]
    out = {"dates": [d.strftime("%Y-%m-%d") for d in idx], "series": {}}
    for key, d in entries:
        s = pd.Series(d["model"], index=pd.to_datetime(d["dates"]), dtype=float)
        s = s.reindex(s.index.union(idx)).ffill().reindex(idx)
        s = s.where(idx >= pd.Timestamp(d["dates"][0]))
        out["series"][key] = [None if pd.isna(x) else round(float(x), 3) for x in s.values]
    for b in BENCH_KEYS:
        if b in bench and bench[b].notna().any():
            s = bench[b].reindex(bench.index.union(idx)).ffill().reindex(idx)
            out["series"][b] = [None if pd.isna(x) else round(float(x), 4) for x in s.values]
    return out


def build(mdl: dict, bes_model: dict | None, bench: pd.DataFrame) -> dict:
    models, daily = [], []
    for key, p in (mdl.get("profiles") or {}).items():
        bt = p.get("backtest") or {}
        if bt.get("available"):
            e = _entry(key, p["label"], "fon", bt["dates"], bt["series"]["model"], bench)
            if e:
                models.append(e)
            if bt.get("daily"):
                daily.append((key, bt["daily"]))
    # Üç BES modeli (Koruyucu / Dengeli / Büyüme), 2 ayda bir yenilenir; aylık noktalar ara aylarda tutuşla okunur
    for key, p in ((bes_model or {}).get("profiles") or {}).items():
        bt = p.get("backtest") or {}
        mo = bt.get("monthly")
        if mo:
            e = _entry(f"bes_{key}", f"BES {p.get('label', key)}", "bes", mo["dates"], mo["model"], bench)
            if e:
                models.append(e)
        if bt.get("daily"):
            daily.append((f"bes_{key}", bt["daily"]))
    return {"asOf": mdl.get("asOf"), "models": models, "daily": _daily(daily, bench)}

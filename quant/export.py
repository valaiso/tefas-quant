"""Statik site için küçük JSON dosyaları üretir (dist/data)."""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from .db import ROOT

SITE_FILES = ["index.html", "assets"]


def _clean(value):
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(value) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_clean(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )


def _r(x, nd=2):
    return None if x is None or pd.isna(x) else round(float(x), nd)


def _fund_record(code: str, f: pd.Series) -> dict:
    return {
        "c": code,
        "n": f["name"],
        "k": f["category"],
        "q": int(f["qualified"]) if not pd.isna(f["qualified"]) else 0,
        "s": _r(f["score"], 1),
        "g": f["grade"],
        "sig": f["signal"],
        "rk": int(f["rank"]),
        "ct": int(f["cat_size"]),
        "pc": _r(f["percentile"], 1),
        "or": int(f["overall_rank"]),
        "cf": _r(f["confidence"], 0),
        "abs": _r(f["absolute"], 1),
        "b": {k: _r(f[f"s_{k}"], 1) for k in config.COMPONENT_WEIGHTS},
        "p": {
            "investor": _r(f["p_investor"], 1),
            "outflow": _r(f["p_outflow"], 1),
            "anomaly": _r(f["p_anomaly"], 1),
        },
        "adj": {"confidence": _r(f["adj_confidence"], 1), "stability": _r(f["adj_stability"], 1)},
        "r": {"1g": _r(f["r_1g"]), **{k: _r(f[f"raw_r_{k}"]) for k in config.PERFORMANCE_WINDOWS}},
        "m": {
            "vol": _r(f["volatility"] * 100),
            "mdd": _r(f["mdd"] * 100),
            "sharpe": _r(f["sharpe"]),
            "sortino": _r(f["sortino"]),
            "calmar": _r(f["calmar"]),
            "beta": _r(f["beta"]),
            "alpha": _r(f["alpha"] * 100),
            "ir": _r(f["information_ratio"]),
            "cagr": _r(f["cagr"] * 100),
        },
        "aum": _r(f["aum"], 0),
        "inv": None if pd.isna(f["investors"]) else int(f["investors"]),
        "ig": _r(f["investor_growth_1m"]),
        "fr": _r(f["flow_ratio"]),
        "fl": {k: _r(f[f"flow_{k}"], 0) for k in ("1w", "1m", "3m")},
        "fee": _r(f["fee"]),
        "st": _r(f["stopaj"]),
        "d0": f["first_date"],
        "hd": int(f["history_days"]),
    }


def _weekly(series: pd.Series) -> pd.Series:
    """Haftanın son fiyatı (cuma ya da haftanın son işlem günü)."""
    s = series.dropna()
    last_rows = ~s.index.to_period("W-FRI").duplicated(keep="last")
    return s[last_rows]


def build(result: dict, out_dir: Path = ROOT / "dist") -> dict:
    scored: pd.DataFrame = result["scored"]
    price: pd.DataFrame = result["panel"]["price"]
    if out_dir.exists():
        shutil.rmtree(out_dir)
    data_dir = out_dir / "data"

    funds = [_fund_record(code, f) for code, f in scored.iterrows()]
    _write(data_dir / "funds.json", funds)

    # Fon başına haftalık kapanış serisi (detay ve karşılaştırma grafiği)
    for code in scored.index:
        w = _weekly(price[code])
        _write(data_dir / "history" / f"{code}.json",
               {"d": [d.strftime("%Y-%m-%d") for d in w.index], "p": [round(float(v), 6) for v in w.values]})

    # Kategori ortalaması: eşit ağırlıklı haftalık endeks (100 tabanlı)
    rets = price[scored.index].pct_change(fill_method=None).clip(-0.5, 1.0)
    categories = {}
    for cat, codes in scored.groupby("category").groups.items():
        idx = (1 + rets[list(codes)].mean(axis=1).fillna(0)).cumprod() * 100
        w = _weekly(idx)
        categories[cat] = {"d": [d.strftime("%Y-%m-%d") for d in w.index], "v": [round(float(v), 3) for v in w.values]}
    _write(data_dir / "categories.json", categories)

    signals = scored["signal"].value_counts().to_dict()
    meta = {
        "lastDataDate": result["as_of"],
        "firstDataDate": result["first_date"],
        "generated": result["generated"],
        "fundCount": len(funds),
        "riskFree": round(result["risk_free"] * 100, 2),
        "signals": signals,
        "excluded": result["excluded"],
        "config": {
            "historyYears": config.HISTORY_YEARS,
            "weights": config.COMPONENT_WEIGHTS,
            "performanceWindows": {k: {"days": d, "weight": w} for k, (d, w) in config.PERFORMANCE_WINDOWS.items()},
            "anomaly": {
                "z": config.ANOMALY_Z_THRESHOLD,
                "perZ": config.ANOMALY_PENALTY_PER_Z,
                "max": config.ANOMALY_MAX_PENALTY,
            },
            "investorPenalties": config.INVESTOR_PENALTIES,
            "outflowPenalties": config.OUTFLOW_PENALTIES,
            "stalePriceDays": config.STALE_PRICE_DAYS,
            "ratingMode": config.RATING_MODE,
        },
    }
    _write(data_dir / "meta.json", meta)

    for name in SITE_FILES:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, out_dir / name)
        elif src.exists():
            shutil.copy2(src, out_dir / name)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return meta

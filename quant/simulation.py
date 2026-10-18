"""Portföy simülasyonu: her ay A+ (GÜÇLÜ AL) fonlardan eşit ağırlıklı sepet.

Kurallar
--------
* Sepet her ay sonu, yalnızca o güne kadar bilinen veriyle verilen A+ notlarından
  kurulur (QuantBacktest ile aynı point-in-time notlar).
* Alış T+1 fiyatından; sepet bir sonraki sinyalin T+1 gününe kadar tutulur ve
  yeniden eşit ağırlıklandırılır. Komisyon yok (TEFAS), stopaj dahil değil.
* Ay içinde fiyatı yayımlanmayı bırakan fon son fiyatıyla değerlenir.
* A+ fon yoksa o ay nakit (PPF ortalaması) tutulur.
* Kıyaslar aynı tarihlerde ölçülür: tüm fonların eşit ağırlıklı sepeti, PPF
  ortalaması, gram altın, dolar/TL ve TÜFE.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _stats(level: pd.Series, monthly: pd.Series, ppf_monthly: pd.Series | None) -> dict:
    level = level.dropna()
    if len(level) < 2:
        return {}
    years = (level.index[-1] - level.index[0]).days / 365.25
    total = level.iloc[-1] / level.iloc[0] - 1
    mdd = float((level / level.cummax() - 1).min())
    out = {
        "total": round(total * 100, 2),
        "cagr": round(((1 + total) ** (1 / years) - 1) * 100, 2) if years > 0 else None,
        "mdd": round(mdd * 100, 2),
        "vol": round(float(monthly.std() * np.sqrt(12) * 100), 2) if len(monthly) > 2 else None,
        "best": round(float(monthly.max() * 100), 2),
        "worst": round(float(monthly.min() * 100), 2),
        "positive": round(float((monthly > 0).mean() * 100), 1),
    }
    if ppf_monthly is not None:
        aligned = pd.concat([monthly, ppf_monthly], axis=1).dropna()
        out["beatPpf"] = round(float((aligned.iloc[:, 0] > aligned.iloc[:, 1]).mean() * 100), 1)
    return out


def run(price: pd.DataFrame, baskets: list[dict], bench: pd.DataFrame,
        category: pd.Series | None = None) -> dict:
    px = price.ffill()
    dates = price.index
    # Yalnızca A+ fonu olan ilk aydan başla (sıkı kural: ilk sinyal ~Ekim 2024)
    first = next((k for k, b in enumerate(baskets) if b["aplus"]), None)
    if first is None:
        return {"available": False}
    baskets = baskets[first:]

    points = [dates[b["signal"] + 1] for b in baskets]  # T+1 alış günleri
    if baskets[-1]["signal"] + 1 < len(dates) - 1:
        points.append(dates[-1])  # son sepet bugüne kadar değerlenir
    ppf_lvl = bench["ppf"]

    def basket_returns(key: str, cat: str | None = None, fallback: str | None = None) -> pd.Series:
        """cat verilirse yalnızca o kategorinin fonları; A+ yoksa `fallback` sepeti tutulur."""
        rets = []
        for k in range(len(points) - 1):
            codes = baskets[k][key]
            if cat is not None:
                codes = [c for c in codes if category.get(c) == cat]
                if not codes and fallback:
                    codes = [c for c in baskets[k][fallback] if category.get(c) == cat]
            a, b = points[k], points[k + 1]
            if codes:
                r = (px.loc[b, codes] / px.loc[a, codes] - 1).dropna()
                r = r.clip(-0.95, 5)
                rets.append(float(r.mean()) if len(r) else 0.0)
            else:
                rets.append(float(ppf_lvl.loc[b] / ppf_lvl.loc[a] - 1))
        return pd.Series(rets, index=points[1:])

    def level_from(rets: pd.Series) -> pd.Series:
        lvl = (1 + rets).cumprod() * 100
        return pd.concat([pd.Series([100.0], index=[points[0]]), lvl])

    def bench_level(col: str) -> pd.Series | None:
        if col not in bench or bench[col].isna().all():
            return None
        s = bench[col].reindex(points)
        return s / s.iloc[0] * 100

    series, stats = {}, {}
    ppf_m = bench_level("ppf").pct_change().dropna()
    for key, label in [("aplus_public", "A+ sepeti"), ("aplus", "A+ sepeti (nitelikli dahil)"),
                       ("universe_public", "Tüm fonlar"), ("universe", "Tüm fonlar (nitelikli dahil)")]:
        r = basket_returns(key)
        lvl = level_from(r)
        series[key] = {"label": label, "v": [round(float(x), 3) for x in lvl.values]}
        stats[key] = _stats(lvl, r, ppf_m)
    for key, label in [("ppf", "PPF ortalaması"), ("gold", "Gram altın"), ("tufe", "TÜFE"), ("usd", "Dolar/TL")]:
        lvl = bench_level(key)
        if lvl is None:
            continue
        series[key] = {"label": label, "v": [None if pd.isna(x) else round(float(x), 3) for x in lvl.values]}
        stats[key] = _stats(lvl, lvl.pct_change().dropna(), ppf_m if key != "ppf" else None)

    # Kategori içi: A+ sepeti, aynı kategorinin tüm fonlarına karşı (notlar kategori içi verildiği için adil kıyas)
    by_cat = {}
    if category is not None:
        cats = sorted({category.get(c) for b in baskets for c in b["aplus_public"]} - {None})
        for cat in cats:
            months_with = sum(any(category.get(c) == cat for c in b["aplus_public"]) for b in baskets[:-1] or baskets)
            if months_with < max(3, len(baskets) // 3):
                continue  # kategoride A+ çok seyrek; anlamlı sepet yok
            ra = basket_returns("aplus_public", cat, fallback="universe_public")
            ru = basket_returns("universe_public", cat)
            la, lu = level_from(ra), level_from(ru)
            by_cat[cat] = {
                "aplus": [round(float(x), 3) for x in la.values],
                "universe": [round(float(x), 3) for x in lu.values],
                "stats": {"aplus": _stats(la, ra, None), "universe": _stats(lu, ru, None)},
                "beat": round(float((ra > ru).mean() * 100), 1),
                "monthsWithAplus": int(months_with),
            }

    holdings = [
        {"date": dates[b["signal"]].strftime("%Y-%m-%d"), "n": len(b["aplus_public"]), "nAll": len(b["aplus"]),
         "codes": b["aplus_public"], "codesAll": b["aplus"]}
        for b in baskets
    ]
    return {
        "available": True,
        "dates": [d.strftime("%Y-%m-%d") for d in points],
        "series": series,
        "stats": stats,
        "holdings": holdings,
        "byCategory": by_cat,
        "rules": "Aylık yeniden dengeleme, eşit ağırlık, T+1 alış, komisyon ve stopaj hariç",
    }

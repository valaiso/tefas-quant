"""QuantBacktest: geçmişte A+ (GÜÇLÜ AL) notu alan fonların sonraki getirileri.

Her ay sonunda skorlar *yalnızca o güne kadar bilinen veriyle* yeniden üretilir
(point-in-time). O tarihte A+ olan her fon için T+1 alış fiyatından sonraki
1A / 3A / 6A / 1Y / 2Y / 3Y getirisi ölçülür. Fon sonradan not kaybetse,
çökse ya da listeden çıksa da o tarihteki A+ gözlemi sayılır; kayıp dahil.

Kıyas: aynı tarihte, aynı kategorideki tüm skorlanan fonların *medyan*
getirisi (ortalama, birkaç aşırı fonla şişebiliyor; ör. +%2.600). "İsabet" =
A+ fonun kendi kategori medyanını geçme oranı.

Sınırlar
--------
* Yönetim ücreti ve kategori bugünkü değerdir (geçmiş kopyası yok).
* FVT'nin işlem durumu bayrağı geçmişte bilinemeyeceği için kullanılmaz.
* A+ canlı skorla aynı sıkı kuralla verilir (üst %5, kalite kapıları, 2 ay
  süreklilik, kurucu riski yok); ilk iki ayda süreklilik ölçülemediği için A+ yok.
* Fiyat yayımı duran bir fon son yayımlanan fiyatla değerlenir (gerçekte
  çıkış mümkün olmayabilir; kayıp eksik ölçülebilir).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import scoring

HORIZONS = {"1a": 21, "3a": 63, "6a": 126, "1y": 252, "2y": 504, "3y": 756}
MIN_HISTORY = 63  # ilk sinyal için evrende gereken işlem günü


GRADES = ["A+", "A", "B", "C", "D"]


def run(panel: dict, funds: pd.DataFrame, grade: str = "A+") -> dict:
    price = panel["price"]
    dates = price.index
    px = price.ffill()  # yayımı duran fon son fiyatıyla değerlenir
    funds_pit = funds.copy()
    funds_pit["trading_active"] = np.nan  # geçmişte bilinemeyen bayrak

    obs = []
    baskets = []  # portföy simülasyonu için her ayın sepetleri
    prev_base: list[pd.Series] = []  # önceki ay sonlarının temel notları (süreklilik şartı)
    signal_dates = [i for i in scoring.month_ends(dates) if i >= MIN_HISTORY and i + 1 < len(dates)]
    for i in signal_dates:
        sub = {k: v.iloc[: i + 1] for k, v in panel.items() if isinstance(v, pd.DataFrame)}
        m, excluded_then, _rf = scoring.compute_metrics(sub, funds_pit, light=True)
        # Canlı skorla aynı kurallar: o tarihteki kurucu riski + sıkı GÜÇLÜ AL
        risky = scoring.founder_risk(funds, m.index, excluded_then)
        flag = funds["founder"].reindex(m.index).isin(risky)
        s = scoring.score_funds(m, founder_flag=flag, prev_grades=prev_base)
        prev_base.append(scoring.score_funds(m)["base_grade"])
        qualified = funds["qualified"].reindex(s.index).fillna(0).astype(bool)
        baskets.append({
            "signal": i,
            "aplus": list(s.index[s["grade"] == "A+"]),
            "aplus_public": list(s.index[(s["grade"] == "A+") & ~qualified]),
            "universe": list(s.index),
            "universe_public": list(s.index[~qualified]),
            # model portföy: o günkü skor, not ve risk bayrakları
            "scores": s[["score", "grade", "p_anomaly", "flag_tail", "flag_hot", "founder_risk"]].copy(),
        })
        entry = i + 1  # T+1: emir ertesi işlem günü fiyatından gerçekleşir
        p0 = px.iloc[entry].reindex(s.index)
        row = {"date": dates[i], "code": s.index, "category": s["category"].values,
               "grade": s["grade"].values, "score": s["score"].values}
        df = pd.DataFrame(row).set_index("code")
        for h, n in HORIZONS.items():
            j = entry + n
            df[h] = (px.iloc[j].reindex(s.index) / p0 - 1).values * 100 if j < len(dates) else np.nan
        obs.append(df.reset_index())
    data = pd.concat(obs, ignore_index=True)

    # Kategori medyanı (aynı tarih, aynı kategori, tüm skorlanan fonlar)
    for h in HORIZONS:
        data[f"{h}_cat"] = data.groupby(["date", "category"])[h].transform("median")

    sel = data[data["grade"] == grade]

    def summary(frame: pd.DataFrame) -> dict:
        out = {}
        for h in HORIZONS:
            x = frame[[h, f"{h}_cat"]].dropna()
            if x.empty:
                out[h] = None
                continue
            out[h] = {
                "mean": round(float(x[h].mean()), 2),
                "median": round(float(x[h].median()), 2),
                "cat": round(float(x[f"{h}_cat"].median()), 2),
                "excess": round(float((x[h] - x[f"{h}_cat"]).median()), 2),
                "hit": round(float((x[h] > x[f"{h}_cat"]).mean() * 100), 1),
                "pos": round(float((x[h] > 0).mean() * 100), 1),
                "n": int(len(x)),
                "dates": int(frame.loc[x.index, "date"].nunique()),
            }
        return out

    by_cat = {cat: summary(g) for cat, g in sel.groupby("category")}
    # Doğrulama: tüm notların aynı ölçülerle karşılaştırması
    by_grade = {g: summary(data[data["grade"] == g]) for g in GRADES}
    by_date = []
    for d, g in sel.groupby("date"):
        by_date.append({
            "date": d.strftime("%Y-%m-%d"),
            "n": int(len(g)),
            "funds": [
                [c, k, *[None if pd.isna(v) else round(float(v), 2) for v in r]]
                for c, k, r in zip(g["code"], g["category"], g[list(HORIZONS)].values)
            ],
        })
    return {
        "grade": grade,
        "entry": "T+1",
        "horizons": HORIZONS,
        "signalDates": [dates[i].strftime("%Y-%m-%d") for i in signal_dates],
        "overall": summary(sel),
        "byCategory": by_cat,
        "byGrade": by_grade,
        "byDate": by_date,
        "observations": int(len(sel)),
        "_baskets": baskets,  # dışa yazılmaz; simulation.run kullanır
    }

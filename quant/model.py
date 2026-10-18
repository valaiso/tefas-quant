"""Model portföy: son 1-2-3 yılda istikrarlı getiri vermiş fonlardan ağırlıklı sepet.

Amaç her kategoriden fon vermek değil; az sayıda (3-10), birbirinden farklı ve
getirisi tek bir sıçramaya dayanmayan fondan oluşan kompakt bir sepet.

Adımlar
-------
1. Aday havuzu: halka açık (nitelikli/özel değil), ≥3 yıl geçmiş, ≥100m TL
   büyüklük, ≥1000 yatırımcı, fiyatı güncel. Bugünkü sepette ayrıca skorda
   dışlanan, anomali / kurucu / kuyruk / sıcak para bayrağı taşıyan fonlar alınmaz.
2. Sıçrama filtresi: 2 yıllık getirinin %40'ından fazlası tek bir aydan
   geliyorsa, son 3 ay kendi geçmişine göre aşırı (z > 2,5) ise ya da son bir
   yılda tek günde ±%15'ten büyük hareket varsa fon elenir.
3. İstikrar şartı: 1Y/2Y/3Y yıllık getirinin hepsinde PPF ortalamasını geçmiş
   ve son 2 yılın 12 aylık dönemlerinin en az %60'ında PPF'yi geçmiş olmalı.
4. Puan (adaylar arasında yüzdelik): getiri 35 (1Y/2Y/3Y yıllık bileşik),
   istikrar 25 (12 aylık dönemlerde PPF'yi geçme oranı), Sharpe 25 (2 yıl),
   düşüş 15 (2 yıllık azami düşüş).
5. Seçim: puan sırasıyla; aynı kategoriden en fazla 2, seçilmiş bir fonla
   haftalık getiri korelasyonu > 0,85 olan fon alınmaz; en az 3, en fazla 10 fon (10 bir tavan, hedef değil).
6. Ağırlık ∝ puan² / oynaklık; her fon %5-%35 aralığında, 5'in katlarına yuvarlanır.

Geçmiş performans: model her ay sonu yalnızca o güne kadar bilinen fiyatlarla
yeniden kurulur, T+1 fiyatından alınır ve bir sonraki aya kadar tutulur.
Geçmişte bayrak/skor dışlama bilgisi kullanılmaz (1-6. adımlar bayraksız).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import scoring
from .simulation import _stats

MIN_FUNDS, MAX_FUNDS = 3, 10
MIN_HISTORY = 756          # 3 yıl işlem günü (1Y/2Y/3Y getirisi ölçülebilsin)
RISK_DAYS = 504            # Sharpe, düşüş ve sıçrama ölçüleri: son 2 yıl
MIN_AUM, MIN_INVESTORS = 100e6, 1000
MAX_PER_CATEGORY = 2
MAX_CORR = 0.85
MIN_W, MAX_W, STEP = 0.05, 0.35, 0.05
SPIKE_SHARE, SPIKE_Z, SPIKE_DAY = 0.40, 2.5, 0.15
WEIGHTS = {"ret": 35, "win": 25, "sharpe": 25, "mdd": 15}
RET_WINDOWS = {"1y": (252, 0.3), "2y": (504, 0.4), "3y": (756, 0.3)}
CASH_CATEGORY = "Para Piyasası"
MIN_BEATS = 3      # 1Y/2Y/3Y'nin hepsinde PPF'yi geçmeli
MIN_WIN = 0.6      # 12 aylık dönemlerin en az %60'ında PPF'yi geçmeli
MIN_SCORE = 40
W_POWER = 2        # ağırlık ∝ puan^W_POWER / oynaklık^V_POWER
V_POWER = 1


def _cagr(px: pd.DataFrame, n: int) -> pd.Series:
    if len(px) <= n:
        return pd.Series(np.nan, index=px.columns)
    total = px.iloc[-1] / px.iloc[-1 - n]
    return total ** (252 / n) - 1


def _metrics(px: pd.DataFrame, ppf: pd.Series) -> pd.DataFrame:
    """px: yalnızca adayların fiyatları (son satır = bugün). ppf aynı tarihlerde."""
    out = pd.DataFrame(index=px.columns)
    for k, (n, _) in RET_WINDOWS.items():
        out[f"cagr_{k}"] = _cagr(px, n)
    ppf_c = {k: float((ppf.iloc[-1] / ppf.iloc[-1 - n]) ** (252 / n) - 1) if len(ppf) > n else np.nan
             for k, (n, _) in RET_WINDOWS.items()}

    last2 = px.iloc[-RISK_DAYS - 1:]
    rets = last2.pct_change(fill_method=None).iloc[1:]
    ppf_r = ppf.iloc[-RISK_DAYS - 1:].pct_change().iloc[1:]
    excess = rets.sub(ppf_r, axis=0)
    out["sharpe"] = excess.mean() / rets.std() * np.sqrt(252)
    out["mdd"] = (last2 / last2.cummax() - 1).min()
    out["vol"] = rets.iloc[-252:].std() * np.sqrt(252)

    # 12 aylık dönemlerde PPF'yi geçme oranı (aylık kaydırmalı, en fazla 24 dönem)
    wins, cnt = pd.Series(0.0, index=px.columns), pd.Series(0.0, index=px.columns)
    for k in range(24):
        e = len(px) - 1 - k * 21
        s = e - 252
        if s < 0:
            break
        fr = px.iloc[e] / px.iloc[s] - 1
        br = ppf.iloc[e] / ppf.iloc[s] - 1
        ok = fr.notna()
        wins += ((fr > br) & ok).astype(float)
        cnt += ok.astype(float)
    out["win"] = (wins / cnt.replace(0, np.nan))

    # Sıçrama ölçüleri
    blocks = last2.iloc[::-21][::-1]                   # 21 günlük bloklar (2 yıl ≈ 24 ay)
    mlog = np.log(blocks / blocks.shift(1)).iloc[1:]
    total_log = mlog.sum()
    out["spike_share"] = (mlog.max() / total_log).where(total_log > 0)
    q = np.log(last2.iloc[::-63][::-1])
    q = (q - q.shift(1)).iloc[1:]
    prev = q.iloc[:-1]
    out["recent_z"] = (q.iloc[-1] - prev.mean()) / prev.std().replace(0, np.nan)
    out["max_day"] = rets.iloc[-252:].abs().max()
    out["beats_ppf"] = sum((out[f"cagr_{k}"] > ppf_c[k]).astype(int) for k in RET_WINDOWS if not np.isnan(ppf_c[k]))
    out.attrs["ppf"] = ppf_c
    return out


def _spike_reason(r: pd.Series) -> str | None:
    if r["spike_share"] > SPIKE_SHARE:
        return f"2 yıllık getirinin %{r['spike_share'] * 100:.0f}'i tek aydan"
    if r["recent_z"] > SPIKE_Z:
        return f"son 3 ay kendi geçmişine göre aşırı (z={r['recent_z']:.1f})"
    if r["max_day"] > SPIKE_DAY:
        return f"son 1 yılda tek günde %{r['max_day'] * 100:.0f} hareket"
    return None


def _pct(s: pd.Series, higher=True) -> pd.Series:
    return s.rank(pct=True, ascending=higher) * 100


def _score(m: pd.DataFrame) -> pd.Series:
    ret = sum(_pct(m[f"cagr_{k}"]).fillna(50) * w for k, (_, w) in RET_WINDOWS.items())
    return (ret * WEIGHTS["ret"] + _pct(m["win"]).fillna(50) * WEIGHTS["win"]
            + _pct(m["sharpe"]).fillna(50) * WEIGHTS["sharpe"]
            + _pct(m["mdd"]).fillna(50) * WEIGHTS["mdd"]) / 100


def _round_weights(raw: pd.Series) -> pd.Series:
    w = raw / raw.sum()
    for _ in range(20):  # sınırları uygula, fazlayı orantılı dağıt
        w = w.clip(MIN_W, MAX_W)
        w = w / w.sum()
        if w.max() <= MAX_W + 1e-9 and w.min() >= MIN_W - 1e-9:
            break
    units = int(round(1 / STEP))
    base = np.floor(w * units).astype(int).clip(lower=1)
    rest = units - base.sum()
    order = (w * units - np.floor(w * units)).sort_values(ascending=False).index
    for c in order:
        if rest <= 0:
            break
        if base[c] < MAX_W * units:
            base[c] += 1
            rest -= 1
    while rest < 0:  # alt sınırdan dolayı fazla çıktıysa en büyükten düş
        c = base.idxmax()
        base[c] -= 1
        rest += 1
    return base * STEP


def build(price: pd.DataFrame, panel: dict, funds: pd.DataFrame, ppf: pd.Series, i: int,
          blocked: dict[str, str] | None = None) -> dict:
    """i. günün (dahil) verisiyle sepeti kurar. blocked: kod -> neden (bugünkü bayraklar)."""
    px_all = price.iloc[: i + 1]
    size, inv = panel["size"].iloc[i], panel["investors"].iloc[i]
    public = ~(funds["qualified"].fillna(0).astype(bool) | funds["private"].fillna(False))
    public = set(funds.index[public])
    hist = px_all.iloc[-MIN_HISTORY - 1]
    recent = px_all.iloc[-10:]
    fresh = recent.notna().any() & (recent.max() != recent.min())
    elig = [c for c in px_all.columns
            if c in public and pd.notna(hist.get(c)) and pd.notna(px_all[c].iloc[-1]) and fresh.get(c, False)
            and size.get(c, 0) >= MIN_AUM and inv.get(c, 0) >= MIN_INVESTORS
            and not (blocked and c in blocked)]
    if not elig:
        return {"funds": [], "candidates": 0}
    px = px_all[elig].ffill()
    m = _metrics(px, ppf.iloc[: i + 1])
    m["spike"] = [_spike_reason(r) for _, r in m.iterrows()]
    clean = m[m["spike"].isna() & (m["beats_ppf"] >= MIN_BEATS) & (m["win"].fillna(0) >= MIN_WIN)].copy()
    clean["score"] = _score(clean)
    clean["category"] = funds["category"].reindex(clean.index)

    wk = px.iloc[-253:].iloc[::5].pct_change().iloc[1:]
    chosen, per_cat = [], {}
    for c in clean.sort_values("score", ascending=False).index:
        if len(chosen) >= MAX_FUNDS:
            break
        cat = clean.at[c, "category"]
        if per_cat.get(cat, 0) >= MAX_PER_CATEGORY:
            continue
        if chosen and wk[chosen].corrwith(wk[c]).max() > MAX_CORR:
            continue
        if len(chosen) >= MIN_FUNDS and clean.at[c, "score"] < MIN_SCORE:
            break
        chosen.append(c)
        per_cat[cat] = per_cat.get(cat, 0) + 1
    # Yeterli fon yoksa en iyi para piyasası fonlarıyla tamamla (nakit ayağı)
    if len(chosen) < MIN_FUNDS:
        cash = m[(funds["category"].reindex(m.index) == CASH_CATEGORY) & ~m.index.isin(chosen)]
        for c in cash.sort_values("cagr_1y", ascending=False).index[: MIN_FUNDS - len(chosen)]:
            chosen.append(c)
            if c not in clean.index:
                clean.loc[c, m.columns] = m.loc[c]
                clean.loc[c, "score"] = 50.0
                clean.loc[c, "category"] = CASH_CATEGORY
    sel = clean.loc[chosen]
    weights = _round_weights(sel["score"] ** W_POWER / sel["vol"].clip(lower=0.02) ** V_POWER)

    # Sıçrama nedeniyle elenen, aksi halde güçlü olan fonlar (bilgi amaçlı)
    spiky = m[m["spike"].notna() & (m["beats_ppf"] >= 2)].copy()  # yalnızca getirisi güçlü görünenler
    spiky["score"] = _score(spiky) if len(spiky) else []
    return {
        "funds": [{"code": c, "w": float(weights[c]), **sel.loc[c].to_dict()} for c in weights.sort_values(ascending=False).index],
        "candidates": len(m),
        "clean": len(clean),
        "spiky": spiky.sort_values("cagr_2y", ascending=False).head(8),
        "ppf": m.attrs["ppf"],
    }


def _r(x, nd=2, mult=100):
    return None if x is None or pd.isna(x) else round(float(x) * mult, nd)


def run(panel: dict, funds: pd.DataFrame, scored: pd.DataFrame, bench: pd.DataFrame) -> dict:
    price = panel["price"]
    dates = price.index
    ppf = bench["ppf"].reindex(dates).ffill()
    px = price.ffill()

    # Bugünkü sepet: skor dışlamaları ve bayraklar da uygulanır
    blocked = {c: "skor dışı" for c in price.columns if c not in scored.index}
    for c, f in scored.iterrows():
        if (f.get("p_anomaly") or 0) > 0:
            blocked[c] = "getiri anomalisi"
        elif f.get("founder_risk"):
            blocked[c] = "kurucu riski"
        elif f.get("flag_tail") or f.get("flag_hot"):
            blocked[c] = "kuyruk riski / sıcak para"
    now = build(price, panel, funds, ppf, len(dates) - 1, blocked)

    def fund_out(f):
        c = f["code"]
        return {
            "c": c, "n": funds.at[c, "name"] if c in funds.index else c, "k": f.get("category"),
            "w": round(f["w"] * 100), "score": round(float(f["score"]), 1),
            "g": scored.at[c, "grade"] if c in scored.index else None,
            "r": {k: _r(f.get(f"cagr_{k}")) for k in RET_WINDOWS},
            "win": _r(f.get("win"), 0), "sharpe": _r(f.get("sharpe"), 2, 1),
            "mdd": _r(f.get("mdd")), "vol": _r(f.get("vol")),
        }

    basket = [fund_out(f) for f in now["funds"]]
    port = {}
    for k in RET_WINDOWS:
        vals = [(b["w"], b["r"][k]) for b in basket if b["r"][k] is not None]
        tw = sum(w for w, _ in vals)
        port[k] = round(sum(w * v for w, v in vals) / tw, 2) if tw else None
    spiky = [{"c": c, "n": funds.at[c, "name"] if c in funds.index else c,
              "k": funds.at[c, "category"] if c in funds.index else None,
              "r2": _r(r["cagr_2y"]), "why": r["spike"]} for c, r in now["spiky"].iterrows()]

    # Geçmiş: her ay sonu point-in-time sepet, T+1 alış, ağırlıklı tutuş
    ends = [i for i in scoring.month_ends(dates) if i >= MIN_HISTORY and i + 1 < len(dates)]
    history, rets, points = [], [], []
    for i in ends:
        b = build(price, panel, funds, ppf, i)
        if b["funds"]:
            history.append({"date": dates[i].strftime("%Y-%m-%d"), "i": i,
                            "items": [[f["code"], round(f["w"] * 100)] for f in b["funds"]]})
    for k, h in enumerate(history):
        a = dates[h["i"] + 1]
        e = dates[history[k + 1]["i"] + 1] if k + 1 < len(history) else dates[-1]
        if e <= a:
            continue
        codes = [c for c, _ in h["items"]]
        w = pd.Series({c: wt / 100 for c, wt in h["items"]})
        r = (px.loc[e, codes] / px.loc[a, codes] - 1).clip(-0.95, 5).fillna(0)
        if not points:
            points.append(a)
        rets.append(float((r * w).sum()))
        points.append(e)
    for h in history:
        h.pop("i")

    backtest = {"available": False}
    if len(rets) >= 3:
        r = pd.Series(rets, index=points[1:])
        lvl = pd.concat([pd.Series([100.0], index=[points[0]]), (1 + r).cumprod() * 100])
        series, stats = {"model": [round(float(x), 3) for x in lvl.values]}, {}
        ppf_l = ppf.reindex(points)
        ppf_m = (ppf_l / ppf_l.iloc[0] * 100).pct_change().dropna()
        stats["model"] = _stats(lvl, r, ppf_m)
        for key in ("ppf", "gold", "tufe", "usd"):
            if key not in bench or bench[key].isna().all():
                continue
            s = bench[key].reindex(points).ffill()
            s = s / s.iloc[0] * 100
            series[key] = [None if pd.isna(x) else round(float(x), 3) for x in s.values]
            stats[key] = _stats(s, s.pct_change().dropna(), ppf_m if key != "ppf" else None)
        backtest = {"available": True, "dates": [d.strftime("%Y-%m-%d") for d in points],
                    "series": series, "stats": stats}

    return {
        "asOf": dates[-1].strftime("%Y-%m-%d"),
        "basket": basket,
        "portfolio": port,
        "ppf": {k: _r(v) for k, v in now.get("ppf", {}).items()},
        "candidates": now["candidates"], "clean": now.get("clean", 0),
        "spiky": spiky,
        "history": history,
        "backtest": backtest,
        "rules": {
            "minFunds": MIN_FUNDS, "maxFunds": MAX_FUNDS, "minHistoryDays": MIN_HISTORY,
            "minAum": MIN_AUM, "minInvestors": MIN_INVESTORS, "maxPerCategory": MAX_PER_CATEGORY,
            "maxCorr": MAX_CORR, "minW": MIN_W, "maxW": MAX_W, "spikeShare": SPIKE_SHARE,
            "spikeZ": SPIKE_Z, "spikeDay": SPIKE_DAY, "weights": WEIGHTS,
            "minBeats": MIN_BEATS, "minWin": MIN_WIN, "minScore": MIN_SCORE,
            "retWindows": {k: w for k, (_, w) in RET_WINDOWS.items()},
        },
    }

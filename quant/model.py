"""Model portföyler: Güvenli, Dengeli ve Atak profilde 3-10 fonluk ağırlıklı sepetler.

Amaç her kategoriden fon vermek değil; son 1-2-3 yılda vergi sonrası istikrarlı
getiri vermiş, TEFAS Quant skoru destekleyen ve getirisi tek bir sıçramaya
dayanmayan az sayıda fondan kompakt bir sepet kurmak.

Dönem
-----
Sepetler 2 ayda bir (çift ayların son işlem günü) kurulur, ertesi işlem günü
(T+1) alınır ve 2 ay tutulur. Yeni dönemde iyi kalan fonlar sepette kalır
(mevcut fona küçük süreklilik avantajı verilir); ağırlıklar yeniden hesaplanır.

Adımlar (her profil için)
-------------------------
1. Aday havuzu: halka açık (nitelikli/özel değil), ≥3 yıl geçmiş, ≥100m TL,
   ≥1000 yatırımcı, fiyatı güncel; o günkü TEFAS Quant notu A+/A/B (C ve D
   alınmaz) ve o gün getiri anomalisi, kuyruk riski, sıcak para ya da kurucu
   riski bayrağı yok; yönetici riski listesindeki kurucuların (ör. Tera
   Portföy) fonları hiç alınmaz.
2. Sıçrama filtresi: 2 yıllık getirinin büyük kısmı tek aydan geliyorsa, son
   3 ay kendi geçmişine göre aşırıysa, tek günde aşırı hareket varsa ya da son
   1 yıl getirisi aşırı yüksekse (profil sınırı) fon alınmaz.
3. Profil kapısı: 1 yıllık oynaklık ve 2 yıllık azami düşüş profil aralığında;
   vergi (stopaj) sonrası getiri profilin kıyas şartını sağlamalı.
4. Puan (havuz içinde yüzdelik): vergi sonrası getiri (1Y/2Y/3Y), istikrar
   (12 aylık dönemlerde PPF'yi geçme oranı), Sharpe, düşüş, TEFAS Quant skoru,
   yatırımcı sayısı ve yönetim ücreti; köklü kurucuya (devlet / büyük özel banka) +2,
   önceki sepette olan fona +3 süreklilik puanı.
5. Seçim: puan sırasıyla; kategori başına sınır, aynı portföy şirketinden tek
   fon, seçilmiş fonla haftalık korelasyonu > 0,85 olan fon alınmaz; en az 3,
   en fazla 10 fon (tavan).
6. Ağırlık ∝ puan² / oynaklık^v; her fon %5-%35, 5'in katlarına yuvarlanır.
   Köklü kurucu dışındaki fon Güvenli'de en fazla %20, Dengeli'de %15 alır
   (tek bir yöneticinin çöküşü sepeti batırmasın; ör. Pardus, Ekim 2026).
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
OK_GRADES = ("A+", "A", "B")
MAX_CORR = 0.85
MIN_W, MAX_W, STEP = 0.05, 0.35, 0.05
SPIKE_SHARE, SPIKE_Z, SPIKE_DAY = 0.40, 2.5, 0.15
PERIOD_MONTHS = 2
BANK_BONUS = 2.0
STAY_BONUS = 3.0
PPF_STOPAJ = 0.175
PPF_TOLERANCE = 0.02     # Güvenli: vergi sonrası yıllık getiri PPF'nin en fazla 2 puan altında
RET_WINDOWS = {"1y": (252, 0.3), "2y": (504, 0.4), "3y": (756, 0.3)}
CASH_CATEGORY = "Para Piyasası"

# Köklü kurucular: devlet bankaları ve büyük özel bankaların portföy şirketleri
BANK_FOUNDERS = {
    "ZİRAAT PORTFÖY", "VAKIF PORTFÖY", "HALK PORTFÖY",            # devlet bankası kökenli
    "İŞ PORTFÖY", "AK PORTFÖY", "GARANTİ PORTFÖY", "YAPI KREDİ PORTFÖY",
    "QNB PORTFÖY", "KUVEYT TÜRK PORTFÖY",                           # büyük özel bankalar
}

# Profil kuralları. beat: vergi sonrası getirinin geçmesi gereken kıyas
#   "ppf_all"  -> 1Y, 2Y, 3Y'nin hepsinde PPF (vergi sonrası)
#   "ppf_near" -> 1Y, 2Y, 3Y'nin hepsinde PPF'ye yakın (en fazla PPF_TOLERANCE altında)
#   "ppf_3y"   -> 3Y yıllıkta PPF ve 1Y/2Y'de TÜFE
#   "tufe_all" -> 1Y, 2Y, 3Y'nin hepsinde TÜFE (reel getiri pozitif)
# safe_share: Dengeli sepetin Güvenli sepete ayrılan payı (oynaklık çapası)
PROFILES = {
    "guvenli": {
        "label": "Güvenli", "vol": (0.0, 0.06), "mdd": -0.05, "beat": "ppf_near", "win": 0.0,
        "max_1y": 1.0, "per_cat": 3, "v_power": 1.0, "min_score": 40, "nonbank_max": 0.20, "bank_min": 0.6,
        "max_corr": None,  # düşük oynaklıklı fonlar faizle birlikte hareket eder; çeşitlilik kurucu ile sağlanır
        "weights": {"ret": 25, "win": 25, "sharpe": 15, "mdd": 10, "quant": 10, "inv": 5, "fee": 10},
    },
    "dengeli": {
        "label": "Dengeli", "vol": (0.04, 0.20), "mdd": -0.20, "beat": "tufe_all", "win": 0.3,
        "max_1y": 1.5, "per_cat": 2, "v_power": 0.5, "min_score": 40, "safe_share": 0.4, "nonbank_max": 0.15, "bank_min": 0.5,
        "weights": {"ret": 30, "win": 15, "sharpe": 20, "mdd": 10, "quant": 10, "inv": 5, "fee": 10},
    },
    "atak": {
        "label": "Atak", "vol": (0.08, 0.35), "mdd": -0.35, "beat": "tufe_all", "win": 0.3,
        "max_1y": 2.0, "per_cat": 2, "v_power": 0.5, "min_score": 40, "min_risky": 0.8, "bank_min": 0.5, "nonbank_max": 0.20,
        "weights": {"ret": 35, "win": 10, "sharpe": 20, "mdd": 10, "quant": 10, "inv": 5, "fee": 10},
    },
}


# Yönetici riski nedeniyle hiçbir profile alınmayan kurucular (kod -> neden).
# Fon dağılımı ve çarpan (F/K, PD/DD) verisi tutulmadığı için bu tür riskler
# elle işaretlenir.
EXCLUDED_FOUNDERS = {
    "TERA PORTFÖY": "grup şirketlerinin hisselerini alarak fiyatını yükselten, çarpanları (F/K, PD/DD) aşırı hisselere yoğunlaşan fonlar",
}


def excluded_founder(founder) -> str | None:
    return EXCLUDED_FOUNDERS.get(" ".join(founder.split())) if isinstance(founder, str) else None


def is_bank(founder) -> bool:
    return isinstance(founder, str) and " ".join(founder.split()) in BANK_FOUNDERS


def _cagr(px: pd.DataFrame, n: int) -> pd.Series:
    if len(px) <= n:
        return pd.Series(np.nan, index=px.columns)
    return (px.iloc[-1] / px.iloc[-1 - n]) ** (252 / n) - 1


def _metrics(px: pd.DataFrame, ppf: pd.Series, tufe: pd.Series | None, stopaj: pd.Series) -> pd.DataFrame:
    """px: adayların fiyatları (son satır = bugün). ppf/tufe aynı tarihlerde."""
    out = pd.DataFrame(index=px.columns)
    tax = stopaj.reindex(px.columns).fillna(17.5).clip(0, 100) / 100
    bench = {}
    for k, (n, _) in RET_WINDOWS.items():
        gross = _cagr(px, n)
        out[f"cagr_{k}"] = gross
        # Stopaj kazanç üzerinden: toplam kazanç × (1 - oran), sonra yıllığa çevrilir
        total = (1 + gross) ** (n / 252) - 1
        out[f"net_{k}"] = (1 + total * (1 - tax)) ** (252 / n) - 1
        p_tot = float(ppf.iloc[-1] / ppf.iloc[-1 - n] - 1)
        t_tot = float(tufe.iloc[-1] / tufe.iloc[-1 - n] - 1) if tufe is not None and pd.notna(tufe.iloc[-1 - n]) else np.nan
        bench[k] = {
            "ppf": (1 + p_tot) ** (252 / n) - 1,
            "ppf_net": (1 + p_tot * (1 - PPF_STOPAJ)) ** (252 / n) - 1,
            "tufe": (1 + t_tot) ** (252 / n) - 1 if pd.notna(t_tot) else np.nan,
        }

    last2 = px.iloc[-RISK_DAYS - 1:]
    rets = last2.pct_change(fill_method=None).iloc[1:]
    ppf_r = ppf.iloc[-RISK_DAYS - 1:].pct_change().iloc[1:]
    out["sharpe"] = rets.sub(ppf_r, axis=0).mean() / rets.std() * np.sqrt(252)
    out["mdd"] = (last2 / last2.cummax() - 1).min()
    out["vol"] = rets.iloc[-252:].std() * np.sqrt(252)

    # 12 aylık dönemlerde PPF'yi geçme oranı (aylık kaydırmalı, son 2 yıl)
    wins, cnt = pd.Series(0.0, index=px.columns), pd.Series(0.0, index=px.columns)
    for k in range(13):
        e = len(px) - 1 - k * 21
        s = e - 252
        if s < 0:
            break
        fr = px.iloc[e] / px.iloc[s] - 1
        br = ppf.iloc[e] / ppf.iloc[s] - 1
        ok = fr.notna()
        wins += ((fr > br) & ok).astype(float)
        cnt += ok.astype(float)
    out["win"] = wins / cnt.replace(0, np.nan)

    # Sıçrama ölçüleri
    blocks = last2.iloc[::-21][::-1]
    mlog = np.log(blocks / blocks.shift(1)).iloc[1:]
    total_log = mlog.sum()
    out["spike_share"] = (mlog.max() / total_log).where(total_log > 0)
    q = np.log(last2.iloc[::-63][::-1])
    q = (q - q.shift(1)).iloc[1:]
    prev = q.iloc[:-1]
    out["recent_z"] = (q.iloc[-1] - prev.mean()) / prev.std().replace(0, np.nan)
    out["max_day"] = rets.iloc[-252:].abs().max()
    out.attrs["bench"] = bench
    return out


def _spike_reason(r: pd.Series, max_1y: float) -> str | None:
    if r["spike_share"] > SPIKE_SHARE:
        return f"2 yıllık getirinin %{r['spike_share'] * 100:.0f}'i tek aydan"
    if r["recent_z"] > SPIKE_Z:
        return f"son 3 ay kendi geçmişine göre aşırı (z={r['recent_z']:.1f})"
    if r["max_day"] > SPIKE_DAY:
        return f"son 1 yılda tek günde %{r['max_day'] * 100:.0f} hareket"
    if r["cagr_1y"] > max_1y:
        return f"1 yıllık getiri %{r['cagr_1y'] * 100:.0f}: aşırı yükseliş"
    return None


def _beats(m: pd.DataFrame, rule: str) -> pd.Series:
    b = m.attrs["bench"]
    if rule == "ppf_all":
        return np.logical_and.reduce([m[f"net_{k}"] > b[k]["ppf_net"] for k in RET_WINDOWS])
    if rule == "ppf_near":  # PPF'ye yakın: her pencerede en fazla PPF_TOLERANCE altında
        return np.logical_and.reduce([m[f"net_{k}"] > b[k]["ppf_net"] - PPF_TOLERANCE for k in RET_WINDOWS])
    if rule == "ppf_3y":
        tufe_ok = [m[f"net_{k}"] > b[k]["tufe"] for k in ("1y", "2y") if pd.notna(b[k]["tufe"])]
        return np.logical_and.reduce([m["net_3y"] > b["3y"]["ppf_net"], *tufe_ok])
    tufe_ok = [m[f"net_{k}"] > b[k]["tufe"] for k in RET_WINDOWS if pd.notna(b[k]["tufe"])]
    return np.logical_and.reduce(tufe_ok) if tufe_ok else pd.Series(True, index=m.index)


def _pct(s: pd.Series, higher=True) -> pd.Series:
    return s.rank(pct=True, ascending=higher) * 100


def _score(m: pd.DataFrame, w: dict) -> pd.Series:
    ret = sum(_pct(m[f"net_{k}"]).fillna(50) * wt for k, (_, wt) in RET_WINDOWS.items())
    parts = {
        "ret": ret,
        "win": _pct(m["win"]).fillna(50),
        "sharpe": _pct(m["sharpe"]).fillna(50),
        "mdd": _pct(m["mdd"]).fillna(50),
        "quant": _pct(m["quant"]).fillna(50),
        "inv": _pct(np.log(m["investors"].clip(lower=1))).fillna(50),
        "fee": _pct(m["fee"], higher=False).fillna(50),
    }
    return sum(parts[k] * w[k] for k in w) / sum(w.values())


def _round_weights(raw: pd.Series, caps: pd.Series | None = None) -> pd.Series:
    """Ağırlıkları %5-üst sınır aralığına sıkıştırıp 5'in katlarına yuvarlar. caps: fon başına üst sınır."""
    caps = (caps if caps is not None else pd.Series(MAX_W, index=raw.index)).reindex(raw.index).fillna(MAX_W)
    if caps.sum() < 1 - 1e-9:  # sınırlarla %100'e ulaşılamıyorsa genel sınıra dön
        caps = pd.Series(MAX_W, index=raw.index)
        if caps.sum() < 1:
            caps[:] = 1.0
    w = raw / raw.sum()
    for _ in range(50):
        w = w.clip(lower=MIN_W).clip(upper=caps)
        excess = 1 - w.sum()
        free = w < caps - 1e-12
        if abs(excess) < 1e-9 or not free.any():
            break
        w[free] += excess * w[free] / w[free].sum()
    units = int(round(1 / STEP))
    cap_u = np.floor(caps * units + 1e-9).astype(int)
    base = np.minimum(np.floor(w * units).astype(int).clip(lower=1), cap_u)
    rest = units - base.sum()
    order = (w * units - np.floor(w * units)).sort_values(ascending=False).index
    while rest > 0:
        moved = False
        for c in order:
            if rest <= 0:
                break
            if base[c] < cap_u[c]:
                base[c] += 1
                rest -= 1
                moved = True
        if not moved:
            break
    while rest < 0:
        c = base.idxmax()
        base[c] -= 1
        rest += 1
    return base * STEP


def universe(price: pd.DataFrame, panel: dict, funds: pd.DataFrame, ppf: pd.Series, tufe: pd.Series | None,
             i: int, scores: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """i. gün (dahil) bilinen veriyle tüm profillerin ortak aday tablosu."""
    px_all = price.iloc[: i + 1]
    size, inv = panel["size"].iloc[i], panel["investors"].iloc[i]
    public = ~(funds["qualified"].fillna(0).astype(bool) | funds["private"].fillna(False))
    public = set(funds.index[public])
    hist = px_all.iloc[-MIN_HISTORY - 1]
    recent = px_all.iloc[-10:]
    fresh = recent.notna().any() & (recent.max() != recent.min())
    grades = scores["grade"] if scores is not None else pd.Series(dtype=object)
    flagged = set()
    if scores is not None:  # o günkü bayraklar: getiri anomalisi, kuyruk riski, sıcak para, kurucu riski
        bad = scores["p_anomaly"].fillna(0) > 0
        for col in ("flag_tail", "flag_hot", "founder_risk"):
            if col in scores:
                bad |= scores[col].fillna(False).astype(bool)
        flagged = set(scores.index[bad])
    elig = [c for c in px_all.columns
            if c in public and pd.notna(hist.get(c)) and pd.notna(px_all[c].iloc[-1]) and fresh.get(c, False)
            and size.get(c, 0) >= MIN_AUM and inv.get(c, 0) >= MIN_INVESTORS
            and not excluded_founder(funds["founder"].get(c))
            and (scores is None or (grades.get(c) in OK_GRADES and c not in flagged))]
    if not elig:
        return pd.DataFrame(), None
    px = px_all[elig].ffill()
    m = _metrics(px, ppf.iloc[: i + 1], tufe.iloc[: i + 1] if tufe is not None else None, funds["stopaj"])
    m["category"] = funds["category"].reindex(m.index)
    m["founder"] = funds["founder"].reindex(m.index)
    m["bank"] = m["founder"].map(is_bank)
    m["fee"] = funds["fee"].reindex(m.index)
    m["stopaj"] = funds["stopaj"].reindex(m.index)
    m["investors"] = inv.reindex(m.index)
    m["aum"] = size.reindex(m.index)
    m["quant"] = scores["score"].reindex(m.index) if scores is not None else np.nan
    m["grade"] = grades.reindex(m.index) if scores is not None else None
    weekly = px.iloc[-253:].iloc[::5].pct_change().iloc[1:]
    return m, weekly


def _gate(m: pd.DataFrame, profile: dict) -> tuple[pd.Series, pd.Series]:
    lo, hi = profile["vol"]
    spike = m.apply(lambda r: _spike_reason(r, profile["max_1y"]), axis=1)
    gate = (m["vol"] > lo) & (m["vol"] <= hi) & (m["mdd"] >= profile["mdd"]) & spike.isna()         & _beats(m, profile["beat"]) & (m["win"].fillna(0) >= profile["win"])
    return gate, spike


def _cap(bank: bool, profile: dict) -> float:
    """Köklü kurucu dışındaki fonun ağırlık sınırı (yönetici / operasyon riski)."""
    return MAX_W if bank else profile.get("nonbank_max", MAX_W)


def _choose(pool: pd.DataFrame, wk: pd.DataFrame, profile: dict, limit: int, taken=(),
            founders=(), cap_room: float = 1.0, enough: int | None = None, against=()) -> list[str]:
    """cap_room: seçilen fonların ağırlık sınırları toplamının ulaşması gereken pay.
    enough: bu kadar fon seçilip sınırlar yettiğinde dur (tamamlama modu).
    against: korelasyon kontrolüne dahil edilecek, başka ayakta seçilmiş fonlar."""
    chosen, per_cat, used = [], {}, set(founders)
    caps = 0.0
    for c in pool.sort_values("score", ascending=False).index:
        if len(chosen) >= limit or (enough is not None and len(chosen) >= enough and caps >= cap_room - 1e-9):
            break
        if c in taken:
            continue
        cat, fd = pool.at[c, "category"], pool.at[c, "founder"]
        if per_cat.get(cat, 0) >= profile["per_cat"]:
            continue
        if isinstance(fd, str) and fd in used:  # aynı portföy şirketinden tek fon
            continue
        max_corr = profile.get("max_corr", MAX_CORR)
        peers = [x for x in (*against, *chosen) if x in wk.columns]
        if peers and max_corr is not None and wk[peers].corrwith(wk[c]).max() > max_corr:
            continue
        if len(chosen) >= MIN_FUNDS and caps >= cap_room - 1e-9 and pool.at[c, "score"] < profile["min_score"]:
            break
        chosen.append(c)
        per_cat[cat] = per_cat.get(cat, 0) + 1
        used.add(fd)
        caps += _cap(bool(pool.at[c, "bank"]), profile)
    return chosen


def pick(m: pd.DataFrame, wk: pd.DataFrame | None, profile: dict, prev: list[str] | None = None,
         safe: dict | None = None) -> dict:
    """Bir profilin sepetini aday tablosundan seçer.

    safe: Güvenli profilin sonucu. Dengeli profilde sepetin `safe_share` kadarı
    Güvenli sepetin fonlarına ayrılır; Atak'ta yalnızca fon sayısı 3'ün altında
    kalırsa nakit ayağı olarak kullanılır.
    """
    if m.empty:
        return {"funds": [], "pool": 0}
    gate, spike = _gate(m, profile)
    pool = m[gate].copy()
    pool["score"] = (_score(pool, profile["weights"]) + pool["bank"] * BANK_BONUS) if len(pool) else []
    if prev and len(pool):
        pool.loc[pool.index.isin(prev), "score"] += STAY_BONUS
    if len(pool):
        pool["score"] = pool["score"].clip(upper=100)

    share = profile.get("safe_share", 0.0)
    safe_funds = [f for f in (safe or {}).get("funds", [])][:3] if share > 0 else []
    taken = {f["code"] for f in safe_funds}
    founders = {f.get("founder") for f in safe_funds}
    bank_min = profile.get("bank_min", 0.0)
    legs = {}  # fon -> ayağın sepetteki payı içindeki grup ("bank" / "all")
    if bank_min and len(pool) and pool["bank"].any():
        # Güvenli: sepetin en az bank_min'i köklü kurucuların fonlarında (karşı taraf / yönetici riski)
        b_pool = pool[pool["bank"]]
        risky_b = _choose(b_pool, wk, profile, MAX_FUNDS - len(safe_funds), taken=taken, founders=founders,
                          cap_room=bank_min * (1 - share), against=list(taken))
        n_pool = pool[~pool["bank"]]
        risky_n = _choose(n_pool, wk, profile, MAX_FUNDS - len(safe_funds) - len(risky_b), taken=taken | set(risky_b),
                          founders=founders | {pool.at[c, "founder"] for c in risky_b},
                          cap_room=(1 - bank_min) * (1 - share), enough=1,
                          against=risky_b + list(taken)) if len(n_pool) else []
        risky = risky_b + risky_n
        legs = {**{c: "bank" for c in risky_b}, **{c: "all" for c in risky_n}}
    else:
        risky = _choose(pool, wk, profile, MAX_FUNDS - len(safe_funds), taken=taken,
                        founders=founders, cap_room=1 - share) if len(pool) else []

    # Güvenli profil 3 fona ulaşamazsa: kapıyı geçemeyen ama düşük oynaklıklı, sıçramasız en iyi fonlar
    if profile.get("fill_low_vol") and len(risky) < MIN_FUNDS:
        extra = m[(m["vol"] <= profile["vol"][1]) & spike.isna() & ~m.index.isin(risky)].copy()
        if len(extra):
            extra["score"] = _score(extra, profile["weights"]) * 0.8 + extra["bank"] * BANK_BONUS
            room = 1 - sum(_cap(bool(pool.at[c, "bank"]), profile) for c in risky)
            for c in _choose(extra, wk, profile, MAX_FUNDS - len(risky), taken=set(risky),
                             founders={pool.at[c, "founder"] for c in risky}, cap_room=room,
                             enough=MIN_FUNDS - len(risky)):
                pool.loc[c] = extra.loc[c]
                risky.append(c)

    cash = []
    if share == 0 and len(risky) < MIN_FUNDS and safe and safe.get("funds"):
        cash = [f["code"] for f in safe["funds"] if f["code"] not in risky][: MIN_FUNDS - len(risky)]

    rows = {c: pool.loc[c].to_dict() for c in risky}
    raw = pd.Series({c: rows[c]["score"] ** 2 / max(rows[c]["vol"], 0.02) ** profile["v_power"] for c in risky}, dtype=float)
    if legs and any(v == "all" for v in legs.values()) and any(v == "bank" for v in legs.values()):
        grp = pd.Series(legs)
        raw = pd.concat([raw[grp == "bank"] / raw[grp == "bank"].sum() * bank_min,
                         raw[grp == "all"] / raw[grp == "all"].sum() * (1 - bank_min)])
    if safe_funds or cash:
        sf = {f["code"]: f for f in (safe["funds"] if safe else [])}
        legs = safe_funds if safe_funds else [sf[c] for c in cash]
        leg_w = pd.Series({f["code"]: f["w"] for f in legs})
        leg_share = share if safe_funds else 1 - profile.get("min_risky", 0.8)
        if raw.empty:
            leg_share = 1.0
        raw = (raw / raw.sum() * (1 - leg_share)) if not raw.empty else raw
        raw = pd.concat([raw, leg_w / leg_w.sum() * leg_share])
        for f in legs:
            rows[f["code"]] = {**{k: v for k, v in f.items() if k not in ("code", "w")}, "cash": True}
    if raw.empty:
        return {"funds": [], "pool": int(len(pool)), "spiky": spike}
    caps = pd.Series({c: _cap(bool(rows[c].get("bank")), profile) for c in raw.index})
    weights = _round_weights(raw, caps)
    return {
        "funds": [{"code": c, "w": float(weights[c]), **{"cash": False, **rows[c]}}
                  for c in weights.sort_values(ascending=False).index],
        "pool": int(gate.sum()),
        "spiky": spike,
    }


def formation_days(dates: pd.DatetimeIndex) -> list[int]:
    """Çift ayların son işlem günleri (Şubat, Nisan, Haziran, Ağustos, Ekim, Aralık)."""
    return [i for i in scoring.month_ends(dates) if dates[i].month % PERIOD_MONTHS == 0]


def _r(x, nd=2, mult=100):
    return None if x is None or pd.isna(x) else round(float(x) * mult, nd)


def run(panel: dict, funds: pd.DataFrame, scored: pd.DataFrame, bench: pd.DataFrame,
        baskets: list[dict] | None = None) -> dict:
    price = panel["price"]
    dates = price.index
    ppf = bench["ppf"].reindex(dates).ffill()
    tufe = bench["tufe"].reindex(dates).ffill() if "tufe" in bench and bench["tufe"].notna().any() else None
    px = price.ffill()
    scores_at = {b["signal"]: b["scores"] for b in (baskets or []) if "scores" in b}

    # 2 ayda bir kurulan sepetler (point-in-time), son kurulan = bugünkü sepet
    forms = [i for i in formation_days(dates) if i >= MIN_HISTORY and i + 1 < len(dates) and (not scores_at or i in scores_at)]
    history = {k: [] for k in PROFILES}
    last = {}
    for i in forms:
        m, wk = universe(price, panel, funds, ppf, tufe, i, scores_at.get(i))
        safe_pick = None
        for key, prof in PROFILES.items():
            prev = [f["code"] for f in history[key][-1]["funds"]] if history[key] else None
            res = pick(m, wk, prof, prev, safe=safe_pick if key != "guvenli" else None)
            if key == "guvenli":
                safe_pick = res
            history[key].append({"i": i, "funds": res["funds"], "pool": res["pool"]})
            last[key] = (res, m)

    def fund_out(f, now_flags):
        c = f["code"]
        return {
            "c": c, "n": funds.at[c, "name"] if c in funds.index else c, "k": f.get("category"),
            "w": round(f["w"] * 100), "score": round(float(f["score"]), 1), "bank": bool(f.get("bank")),
            "cash": bool(f.get("cash")), "fd": f.get("founder"), "g": f.get("grade"),
            "gNow": scored.at[c, "grade"] if c in scored.index else None,
            "r": {k: _r(f.get(f"cagr_{k}")) for k in RET_WINDOWS},
            "net": {k: _r(f.get(f"net_{k}")) for k in RET_WINDOWS},
            "st": _r(f.get("stopaj"), 1, 1), "fee": _r(f.get("fee"), 2, 1),
            "inv": None if pd.isna(f.get("investors")) else int(f["investors"]),
            "win": _r(f.get("win"), 0), "sharpe": _r(f.get("sharpe"), 2, 1),
            "mdd": _r(f.get("mdd")), "vol": _r(f.get("vol")),
            "warn": now_flags.get(c),
        }

    # Bugün: dönem içindeki uyarılar (sepet değişmez, bilgi verilir)
    flags = {}
    for c, f in scored.iterrows():
        if (f.get("p_anomaly") or 0) > 0:
            flags[c] = "getiri anomalisi"
        elif f.get("founder_risk"):
            flags[c] = "kurucu riski"
        elif f.get("flag_tail") or f.get("flag_hot"):
            flags[c] = "kuyruk riski / sıcak para"
        elif f.get("grade") in ("C", "D"):
            flags[c] = f"notu {f['grade']} seviyesine düştü"
    for c in {f["code"] for k in history for h in history[k][-1:] for f in h["funds"]}:
        if c not in scored.index:
            flags[c] = "artık skorlanmıyor"

    profiles_out = {}
    for key, prof in PROFILES.items():
        hist = history[key]
        if not hist:
            continue
        cur = hist[-1]
        i0 = cur["i"]
        entry = dates[i0 + 1]
        basket = [fund_out(f, flags) for f in cur["funds"]]
        port = {}
        for k in RET_WINDOWS:
            for field in ("r", "net"):
                vals = [(b["w"], b[field][k]) for b in basket if b[field][k] is not None]
                tw = sum(w for w, _ in vals)
                port[f"{field}_{k}"] = round(sum(w * v for w, v in vals) / tw, 2) if tw else None
        vols = [(b["w"], b["vol"]) for b in basket if b["vol"] is not None]
        port["vol"] = round(sum(w * v for w, v in vols) / 100, 2) if vols else None
        # Dönem başından bugüne sepet getirisi
        if basket:
            w = pd.Series({b["c"]: b["w"] / 100 for b in basket})
            r = (px.iloc[-1][w.index] / px.loc[entry, w.index] - 1).fillna(0)
            since = round(float((r * w).sum()) * 100, 2)
        else:
            since = None
        res, m = last[key]
        spiky = []
        if res.get("spiky") is not None and not m.empty:
            sp = m[res["spiky"].notna() & (m["vol"] <= prof["vol"][1])]
            for c, row in sp.sort_values("net_2y", ascending=False).head(6).iterrows():
                spiky.append({"c": c, "n": funds.at[c, "name"] if c in funds.index else c, "k": row["category"],
                              "r1": _r(row["cagr_1y"]), "why": res["spiky"][c]})

        # Geçmiş performans: her dönem T+1 alış, 2 ay tutuş
        rets, points, items = [], [], []
        for k, h in enumerate(hist):
            a = dates[h["i"] + 1]
            e = dates[hist[k + 1]["i"] + 1] if k + 1 < len(hist) else dates[-1]
            items.append({"date": dates[h["i"]].strftime("%Y-%m-%d"), "pool": h["pool"],
                          "items": [[f["code"], round(f["w"] * 100)] for f in h["funds"]]})
            if e <= a:
                continue
            if h["funds"]:
                w = pd.Series({f["code"]: f["w"] for f in h["funds"]})
                r = (px.loc[e, w.index] / px.loc[a, w.index] - 1).clip(-0.95, 5).fillna(0)
                ret = float((r * w).sum())
            else:
                ret = float(ppf.loc[e] / ppf.loc[a] - 1)
            if not points:
                points.append(a)
            rets.append(ret)
            points.append(e)
        backtest = {"available": False}
        if len(rets) >= 2:
            rs = pd.Series(rets, index=points[1:])
            lvl = pd.concat([pd.Series([100.0], index=[points[0]]), (1 + rs).cumprod() * 100])
            series, stats = {"model": [round(float(x), 3) for x in lvl.values]}, {}
            ppf_l = ppf.reindex(points)
            ppf_p = (ppf_l / ppf_l.iloc[0] * 100).pct_change().dropna()
            stats["model"] = _stats(lvl, rs, ppf_p)
            for b in ("ppf", "gold", "tufe", "usd"):
                if b not in bench or bench[b].isna().all():
                    continue
                s = bench[b].reindex(points).ffill()
                s = s / s.iloc[0] * 100
                series[b] = [None if pd.isna(x) else round(float(x), 3) for x in s.values]
                stats[b] = _stats(s, s.pct_change().dropna(), ppf_p if b != "ppf" else None)
            backtest = {"available": True, "dates": [d.strftime("%Y-%m-%d") for d in points],
                        "series": series, "stats": stats}

        bm = m.attrs.get("bench", {}) if not m.empty else {}
        profiles_out[key] = {
            "label": prof["label"],
            "formed": dates[i0].strftime("%Y-%m-%d"),
            "entry": entry.strftime("%Y-%m-%d"),
            "basket": basket, "portfolio": port, "sinceEntry": since, "pool": cur["pool"],
            "bench": {k: {"ppf": _r(v["ppf"]), "ppfNet": _r(v["ppf_net"]), "tufe": _r(v["tufe"])} for k, v in bm.items()},
            "spiky": spiky, "history": items, "backtest": backtest,
            "rules": {"vol": prof["vol"], "mdd": prof["mdd"], "beat": prof["beat"], "win": prof["win"],
                      "max1y": prof["max_1y"], "perCat": prof["per_cat"], "weights": prof["weights"]},
        }

    nxt = None
    if forms:
        last_form = dates[forms[-1]]
        y, mth = last_form.year, last_form.month + PERIOD_MONTHS
        if mth > 12:
            y, mth = y + 1, mth - 12
        nxt = (pd.Timestamp(year=y, month=mth, day=1) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
    return {
        "asOf": dates[-1].strftime("%Y-%m-%d"),
        "nextRebalance": nxt,
        "candidates": int(len(last["guvenli"][1])) if "guvenli" in last else 0,
        "profiles": profiles_out,
        "rules": {
            "minFunds": MIN_FUNDS, "maxFunds": MAX_FUNDS, "minHistoryDays": MIN_HISTORY,
            "minAum": MIN_AUM, "minInvestors": MIN_INVESTORS, "okGrades": OK_GRADES, "maxCorr": MAX_CORR,
            "minW": MIN_W, "maxW": MAX_W, "spikeShare": SPIKE_SHARE, "spikeZ": SPIKE_Z, "spikeDay": SPIKE_DAY,
            "periodMonths": PERIOD_MONTHS, "bankBonus": BANK_BONUS, "stayBonus": STAY_BONUS,
            "ppfStopaj": PPF_STOPAJ, "banks": sorted(BANK_FOUNDERS),
            "excludedFounders": [{"name": k, "why": v, "funds": int((funds["founder"].map(excluded_founder) == v).sum())}
                                 for k, v in EXCLUDED_FOUNDERS.items()],
            "retWindows": {k: w for k, (_, w) in RET_WINDOWS.items()},
        },
    }

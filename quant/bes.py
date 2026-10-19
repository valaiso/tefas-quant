"""BES (bireysel emeklilik) fonları: sınıflama, skorlama ve uzun vadeli model.

Yatırım fonlarından farkları
----------------------------
* Fon yalnızca kendi emeklilik şirketinle yaptığın sözleşme içinden seçilir;
  model bu yüzden her şirket için ayrı kurulur.
* Birikim döneminde fon getirisinden stopaj kesilmez; vergi çıkışta, birikimin
  getirisi üzerinden alınır. Fon işletim gideri (yıllık ücret) fiyata yansıdığı
  için fiyat getirisi zaten ücret sonrasıdır.
* Devlet katkısı, OKS (otomatik katılım) ve grup fonları serbestçe seçilemez;
  sıralamada kendi kategorilerinde görünür, modele alınmaz.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import backtest, config, model, scoring
from .categorize import categorize
from .simulation import _stats

# Ünvandaki şirket adı -> (kısa ad, satış kanalı bankası; None = acente/aracı)
COMPANIES = [
    (r"^ANADOLU HAYAT", "Anadolu Hayat", "İş Bankası"),
    (r"^AGESA", "AgeSA", "Akbank"),
    (r"^GARANT[İI] EMEKL", "Garanti Emeklilik", "Garanti BBVA"),
    (r"^ALLIANZ YA[ŞS]AM", "Allianz Yaşam", "Yapı Kredi"),
    (r"^ALLIANZ HAYAT", "Allianz Hayat", None),
    (r"^T[ÜU]RK[İI]YE HAYAT", "Türkiye Hayat", "Ziraat Bankası, Halkbank, VakıfBank"),
    (r"^HDI F[İI]BA", "HDI Fiba", "Fibabanka"),
    (r"^BNP PAR[İI]BAS", "BNP Paribas Cardif", "TEB"),
    (r"^QNB", "QNB Sağlık Hayat", "QNB"),
    (r"^KATILIM EMEKL", "Katılım Emeklilik", "Kuveyt Türk, Albaraka"),
    (r"^BEREKET", "Bereket Emeklilik", None),
    (r"^METL[İI]FE", "MetLife", None),
    (r"^AXA", "AXA Hayat", None),
    (r"^ZURICH", "Zurich Yaşam", None),
    (r"^V[İI]ENNAL[İI]FE", "Viennalife", None),
]
_COMPANY_RE = [(re.compile(p), short, bank) for p, short, bank in COMPANIES]

# Serbestçe seçilemeyen fon aileleri (sıra önemli)
ACCESS = [
    ("Devlet Katkısı", "DK", r"KATKI"),
    ("OKS", "OKS", r"\bOKS\b|OTOMAT[İI]K KATILIM"),
    ("Grup", "GRUP", r"\bGRUP\b"),
]
_ACCESS_RE = [(cat, code, re.compile(p)) for cat, code, p in ACCESS]
FOREIGN_RE = re.compile(r"YABANCI|S&P|NASDAQ|ABD|DOLAR|AMER[İI]KA|GLOBAL|ULUSLARARASI|D[ÖO]V[İI]Z|EUROBOND|AVRUPA|EMT[İI]A|D[IİI][ŞS] BOR[ÇC]LANMA|D[IİI][ŞS] K[İI]RA")
TECH_RE = re.compile(r"TEKNOLOJ[İI]")


def company_of(name: str) -> tuple[str, str | None]:
    text = (name or "").upper().strip()
    for rx, short, bank in _COMPANY_RE:
        if rx.search(text):
            return short, bank
    head = text.split(" A.Ş")[0].split(" EMEKL")[0]
    return head.title()[:30] or "Diğer", None


def bes_category(name: str) -> tuple[str, str]:
    """(kategori, erişim kodu). Erişim: "" serbest, "DK" / "OKS" / "GRUP" kısıtlı."""
    text = (name or "").upper()
    for cat, code, rx in _ACCESS_RE:
        if rx.search(text):
            return cat, code
    if re.search(r"BA[ŞS]LANGI[ÇC]", text):
        return "Başlangıç", ""
    if re.search(r"STANDART", text):
        return "Standart", ""
    if re.search(r"YA[ŞS]AM D[ÖO]NG[ÜU]S[ÜU]", text):
        return "Karma", ""                       # hedef tarihli (yaşam döngüsü) fonlar
    cat = categorize(text)
    if cat == "Endeks":
        return "Hisse Senedi", ""                # BES endeks fonları hisse endeksidir
    return cat, ""


def load_funds(conn) -> pd.DataFrame:
    funds = pd.read_sql("SELECT code, name FROM bes_funds", conn).set_index("code")
    cats = [bes_category(n) for n in funds["name"]]
    comp = [company_of(n) for n in funds["name"]]
    funds["category"] = [c for c, _ in cats]
    funds["access"] = [a for _, a in cats]
    funds["company"] = [c for c, _ in comp]
    funds["channel"] = [b for _, b in comp]
    funds["foreign"] = funds["name"].fillna("").str.upper().str.contains(FOREIGN_RE)
    funds["tech"] = funds["name"].fillna("").str.upper().str.contains(TECH_RE)
    funds["founder"] = funds["company"]          # kurucu riski şirket düzeyinde
    funds["category_src"] = "ünvan"
    funds["fee"] = np.nan                        # fon işletim gideri fiyata yansır
    funds["stopaj"] = 0.0                        # birikim döneminde stopaj yok
    funds["trading_active"] = np.nan
    funds["is_serbest"] = 0
    funds["private"] = False
    funds["qualified"] = 0
    return funds


def run(conn) -> dict | None:
    """BES fonlarını yatırım fonlarıyla aynı kurallarla kategori içinde skorlar."""
    panel = scoring.load_panel(conn, "bes_prices")
    if panel["price"].empty or len(panel["price"]) < scoring.MIN_HISTORY_FOR_GRADES:
        print("[bes] yeterli veri yok, atlanıyor", flush=True)
        return None
    funds = load_funds(conn)
    metrics, excluded, rf = scoring.compute_metrics(panel, funds)
    funds_pit = funds.copy()
    ends = [i for i in scoring.month_ends(panel["price"].index) if i >= scoring.MIN_HISTORY_FOR_GRADES]
    prev = [scoring.base_grades_at(panel, funds_pit, i) for i in ends[-config.STRONG_BUY["streak_months"]:]]
    risky = scoring.founder_risk(funds, metrics.index, excluded)
    flag = funds["founder"].reindex(metrics.index).isin(risky)
    scored = scoring.score_funds(metrics, founder_flag=flag, prev_grades=prev)
    scored = scored.join(funds[["name", "qualified", "category_src", "founder"]], how="left")
    print(f"[bes] {panel['price'].index[-1].date()}: {len(scored)} BES fonu skorlandı, {len(excluded)} dışlandı",
          flush=True)
    return {"panel": panel, "funds": funds, "scored": scored, "excluded": excluded, "risk_free": rf,
            "founder_risk": risky, "as_of": panel["price"].index[-1].strftime("%Y-%m-%d"),
            "first_date": panel["price"].index[0].strftime("%Y-%m-%d")}


# =================================================================== model

MIN_FUNDS, MAX_FUNDS = 3, 6
MIN_W, MAX_W, STEP = 0.10, 0.40, 0.05   # BES dağılımında fon başına %10'un altı pratik değil
MIN_HISTORY = 756                        # 3 yıl
MIN_AUM, MIN_INVESTORS = 50e6, 1000
MIN_VOL = 0.06                           # PPF benzeri (para piyasası, kısa vade) fon alınmaz
EXCLUDED_CATEGORIES = {"Para Piyasası", "Borçlanma Araçları", "Standart", "Başlangıç",
                       "Devlet Katkısı", "OKS", "Grup"}
OK_GRADES = ("A+", "A", "B")
MAX_CORR = 0.85
PER_CAT = 2
MAX_1Y = 2.0
STAY_BONUS = 3.0
PERIOD_MONTHS = 2
WEIGHTS = {"ret": 35, "real": 15, "sharpe": 20, "mdd": 15, "quant": 10, "inv": 5}
RET_WINDOWS = {"1y": (252, 0.2), "3y": (756, 0.5), "5y": (1260, 0.3)}


def _metrics(px: pd.DataFrame, rf_idx: pd.Series, tufe: pd.Series | None) -> pd.DataFrame:
    """Uzun vade ölçüleri. px son satır = bugün."""
    m = model._metrics(px, rf_idx, tufe, pd.Series(0.0, index=px.columns))  # sıçrama, Sharpe, oynaklık
    for k, (n, _) in RET_WINDOWS.items():
        m[f"cagr_{k}"] = model._cagr(px, n)
    last3 = px.iloc[-MIN_HISTORY - 1:]
    m["mdd3"] = (last3 / last3.cummax() - 1).min()
    # Reel istikrar: son 3 yılda aylık kaydırılan 12 aylık dönemlerin kaçında TÜFE'yi geçti
    if tufe is not None:
        wins, cnt = pd.Series(0.0, index=px.columns), pd.Series(0.0, index=px.columns)
        for k in range(25):
            e = len(px) - 1 - k * 21
            s = e - 252
            if s < 0 or pd.isna(tufe.iloc[s]) or pd.isna(tufe.iloc[e]):
                continue
            fr = px.iloc[e] / px.iloc[s] - 1
            br = tufe.iloc[e] / tufe.iloc[s] - 1
            ok = fr.notna()
            wins += ((fr > br) & ok).astype(float)
            cnt += ok.astype(float)
        m["real_win"] = wins / cnt.replace(0, np.nan)
        t3 = tufe.iloc[-1] / tufe.iloc[-1 - MIN_HISTORY] if len(tufe) > MIN_HISTORY else np.nan
        m["real_3y"] = (1 + m["cagr_3y"]) / (t3 ** (1 / 3)) - 1 if pd.notna(t3) else np.nan
    else:
        m["real_win"] = np.nan
        m["real_3y"] = np.nan
    return m


def _score(p: pd.DataFrame) -> pd.Series:
    pct = model._pct
    ret = sum(pct(p[f"cagr_{k}"].fillna(p["cagr_3y"])).fillna(50) * w for k, (_, w) in RET_WINDOWS.items())
    parts = {
        "ret": ret, "real": pct(p["real_win"]).fillna(50), "sharpe": pct(p["sharpe"]).fillna(50),
        "mdd": pct(p["mdd3"]).fillna(50), "quant": pct(p["quant"]).fillna(50),
        "inv": pct(np.log(p["investors"].clip(lower=1))).fillna(50),
    }
    return sum(parts[k] * w for k, w in WEIGHTS.items()) / sum(WEIGHTS.values())


def _round(raw: pd.Series) -> pd.Series:
    w = raw / raw.sum()
    max_w = max(MAX_W, 1 / len(w))  # az fonda (1-2) tavan %100'e ulaşacak kadar açılır
    for _ in range(50):
        w = w.clip(MIN_W, max_w)
        w = w / w.sum()
        if w.max() <= max_w + 1e-9 and w.min() >= MIN_W - 1e-9:
            break
    units = int(round(1 / STEP))
    lo, hi = int(round(MIN_W * units)), int(np.ceil(max_w * units - 1e-9))
    base = np.clip(np.floor(w * units).astype(int), lo, hi)
    rest = units - base.sum()
    order = (w * units - np.floor(w * units)).sort_values(ascending=False).index
    while rest > 0:
        moved = False
        for c in order:
            if rest > 0 and base[c] < hi:
                base[c] += 1
                rest -= 1
                moved = True
        if not moved:
            break
    while rest < 0:
        c = base[base > lo].idxmax()
        base[c] -= 1
        rest += 1
    return base * STEP


def _universe(price, panel, funds, rf_idx, tufe, i, scores) -> pd.DataFrame:
    px_all = price.iloc[: i + 1]
    if len(px_all) <= MIN_HISTORY:
        return pd.DataFrame(), None
    size, inv = panel["size"].iloc[i], panel["investors"].iloc[i]
    hist = px_all.iloc[-MIN_HISTORY - 1]
    recent = px_all.iloc[-10:]
    fresh = recent.notna().any() & (recent.max() != recent.min())
    flagged = set()
    if scores is not None:
        bad = scores["p_anomaly"].fillna(0) > 0
        for col in ("flag_tail", "flag_hot", "founder_risk"):
            if col in scores:
                bad |= scores[col].fillna(False).astype(bool)
        flagged = set(scores.index[bad])
    grades = scores["grade"] if scores is not None else pd.Series(dtype=object)
    elig = [c for c in px_all.columns
            if c in funds.index and funds.at[c, "access"] == "" and funds.at[c, "category"] not in EXCLUDED_CATEGORIES
            and pd.notna(hist.get(c)) and pd.notna(px_all[c].iloc[-1]) and fresh.get(c, False)
            and size.get(c, 0) >= MIN_AUM and inv.get(c, 0) >= MIN_INVESTORS
            and (scores is None or (grades.get(c) in OK_GRADES and c not in flagged))]
    if not elig:
        return pd.DataFrame(), None
    px = px_all[elig].ffill()
    m = _metrics(px, rf_idx.iloc[: i + 1], tufe.iloc[: i + 1] if tufe is not None else None)
    m["company"] = funds["company"].reindex(m.index)
    m["category"] = funds["category"].reindex(m.index)
    m["foreign"] = funds["foreign"].reindex(m.index)
    m["investors"] = inv.reindex(m.index)
    m["aum"] = size.reindex(m.index)
    m["quant"] = scores["score"].reindex(m.index) if scores is not None else np.nan
    m["grade"] = grades.reindex(m.index) if scores is not None else None
    m.attrs = {}
    return m, px.iloc[-253:].iloc[::5].pct_change().iloc[1:]


def _pick(m: pd.DataFrame, wk: pd.DataFrame | None, company: str, prev: list[str] | None) -> list[dict]:
    if m.empty:
        return []
    c = m[m["company"] == company].copy()
    if c.empty:
        return []
    spike = c.apply(lambda r: model._spike_reason(r, MAX_1Y), axis=1)
    tufe_ok = c["real_3y"] > 0 if c["real_3y"].notna().any() else pd.Series(True, index=c.index)
    gate = (c["vol"] >= MIN_VOL) & spike.isna() & tufe_ok
    pool = c[gate].copy()
    if pool.empty:
        return []
    pool["score"] = _score(pool)
    if prev:
        pool.loc[pool.index.isin(prev), "score"] += STAY_BONUS
    chosen, per_cat = [], {}
    for code in pool.sort_values("score", ascending=False).index:
        if len(chosen) >= MAX_FUNDS:
            break
        cat = pool.at[code, "category"]
        if per_cat.get(cat, 0) >= PER_CAT:
            continue
        if chosen and wk[chosen].corrwith(wk[code]).max() > MAX_CORR:
            continue
        if len(chosen) >= MIN_FUNDS and pool.at[code, "score"] < 40:
            break
        chosen.append(code)
        per_cat[cat] = per_cat.get(cat, 0) + 1
    # Az fon kaldıysa ikinci tur: korelasyon ve kategori sınırı olmadan en iyi fonlarla 3'e tamamla
    if len(chosen) < MIN_FUNDS:
        for code in pool.sort_values("score", ascending=False).index:
            if len(chosen) >= MIN_FUNDS:
                break
            if code not in chosen:
                chosen.append(code)
    if not chosen:
        return []
    sel = pool.loc[chosen]
    weights = _round(sel["score"] ** 2 / sel["vol"].clip(lower=0.05) ** 0.5)
    return [{"code": k, "w": float(weights[k]), **sel.loc[k].to_dict()} for k in weights.sort_values(ascending=False).index]


def _r(x, nd=2, mult=100):
    return None if x is None or pd.isna(x) else round(float(x) * mult, nd)


def model_run(res: dict, bench: pd.DataFrame) -> dict:
    panel, funds, scored = res["panel"], res["funds"], res["scored"]
    price = panel["price"]
    dates = price.index
    px = price.ffill()
    tufe = bench["tufe"].reindex(dates).ffill() if "tufe" in bench and bench["tufe"].notna().any() else None
    # Risksiz kıyas: BES para piyasası fonlarının eşit ağırlıklı endeksi
    pp = [c for c in funds.index[funds["category"] == "Para Piyasası"] if c in price.columns]
    rf_idx = (1 + price[pp].pct_change(fill_method=None).clip(-0.05, 0.05).mean(axis=1).fillna(0)).cumprod() * 100

    bt = backtest.run(panel, funds)
    scores_at = {b["signal"]: b["scores"] for b in bt.pop("_baskets")}
    forms = [i for i in scoring.month_ends(dates) if dates[i].month % PERIOD_MONTHS == 0
             and i >= MIN_HISTORY and i + 1 < len(dates) and i in scores_at]
    companies = sorted({c for c in funds.loc[funds.index.isin(price.columns), "company"]})
    history = {c: [] for c in companies}
    unis = {}
    for i in forms:
        unis[i], wk = _universe(price, panel, funds, rf_idx, tufe, i, scores_at.get(i))
        for comp in companies:
            prev = [f["code"] for f in history[comp][-1]["funds"]] if history[comp] else None
            history[comp].append({"i": i, "funds": _pick(unis[i], wk, comp, prev)})

    flags = {}
    for code, f in scored.iterrows():
        if (f.get("p_anomaly") or 0) > 0:
            flags[code] = "getiri anomalisi"
        elif f.get("founder_risk"):
            flags[code] = "kurucu riski"
        elif f.get("flag_tail") or f.get("flag_hot"):
            flags[code] = "kuyruk riski / sıcak para"
        elif f.get("grade") in ("C", "D"):
            flags[code] = f"notu {f['grade']} seviyesine düştü"

    out = {}
    for comp in companies:
        hist = history[comp]
        if not hist or not hist[-1]["funds"]:
            continue
        cur = hist[-1]
        entry = dates[cur["i"] + 1]
        basket = []
        for f in cur["funds"]:
            code = f["code"]
            basket.append({
                "c": code, "n": funds.at[code, "name"], "k": f.get("category"), "w": round(f["w"] * 100),
                "score": round(float(f["score"]), 1), "g": f.get("grade"),
                "gNow": scored.at[code, "grade"] if code in scored.index else None,
                "fx": bool(f.get("foreign")), "tk": bool(funds.at[code, "tech"]),
                "r": {k: _r(f.get(f"cagr_{k}")) for k in RET_WINDOWS},
                "real3": _r(f.get("real_3y")), "realWin": _r(f.get("real_win"), 0),
                "sharpe": _r(f.get("sharpe"), 2, 1), "mdd": _r(f.get("mdd3")), "vol": _r(f.get("vol")),
                "inv": None if pd.isna(f.get("investors")) else int(f["investors"]),
                "warn": flags.get(code) or (None if code in scored.index else "artık skorlanmıyor"),
            })
        w = pd.Series({b["c"]: b["w"] / 100 for b in basket})
        since = float(((px.iloc[-1][w.index] / px.loc[entry, w.index] - 1).fillna(0) * w).sum()) * 100
        port = {k: None for k in RET_WINDOWS}
        for k in RET_WINDOWS:
            vals = [(b["w"], b["r"][k]) for b in basket if b["r"][k] is not None]
            tw = sum(x for x, _ in vals)
            port[k] = round(sum(x * v for x, v in vals) / tw, 2) if tw else None

        # Geçmiş: her dönem T+1 alış, bir sonraki kuruluma kadar tutuş; boş dönemde şirketin uygun fonları eşit ağırlık
        rets, points, items = [], [], []
        for k, h in enumerate(hist):
            a = dates[h["i"] + 1]
            e = dates[hist[k + 1]["i"] + 1] if k + 1 < len(hist) else dates[-1]
            items.append({"date": dates[h["i"]].strftime("%Y-%m-%d"),
                          "items": [[f["code"], round(f["w"] * 100)] for f in h["funds"]]})
            if e <= a:
                continue
            if h["funds"]:
                ws = pd.Series({f["code"]: f["w"] for f in h["funds"]})
            else:
                u = unis[h["i"]]
                codes = list(u.index[u["company"] == comp]) if not u.empty else []
                if not codes:
                    continue
                ws = pd.Series(1 / len(codes), index=codes)
            r = (px.loc[e, ws.index] / px.loc[a, ws.index] - 1).clip(-0.95, 5).fillna(0)
            if not points:
                points.append(a)
            rets.append(float((r * ws).sum()))
            points.append(e)
        backtest_out = {"available": False}
        if len(rets) >= 2:
            rs = pd.Series(rets, index=points[1:])
            lvl = pd.concat([pd.Series([100.0], index=[points[0]]), (1 + rs).cumprod() * 100])
            series, stats = {"model": [round(float(x), 3) for x in lvl.values]}, {}
            stats["model"] = _stats(lvl, rs, None)
            for b in ("gold", "usd", "tufe", "ppf"):
                if b not in bench or bench[b].isna().all():
                    continue
                s = bench[b].reindex(points).ffill()
                s = s / s.iloc[0] * 100
                series[b] = [None if pd.isna(x) else round(float(x), 3) for x in s.values]
                stats[b] = _stats(s, s.pct_change().dropna(), None)
            backtest_out = {"available": True, "dates": [d.strftime("%Y-%m-%d") for d in points],
                            "series": series, "stats": stats}
        out[comp] = {
            "company": comp, "channel": funds.loc[funds["company"] == comp, "channel"].dropna().iloc[0]
            if funds.loc[funds["company"] == comp, "channel"].notna().any() else None,
            "formed": dates[cur["i"]].strftime("%Y-%m-%d"), "entry": entry.strftime("%Y-%m-%d"),
            "basket": basket, "portfolio": port, "sinceEntry": round(since, 2),
            "history": items, "backtest": backtest_out,
        }

    nxt = None
    if forms:
        last = dates[forms[-1]]
        y, mth = last.year, last.month + PERIOD_MONTHS
        if mth > 12:
            y, mth = y + 1, mth - 12
        nxt = (pd.Timestamp(year=y, month=mth, day=1) + pd.offsets.BMonthEnd(0)).strftime("%Y-%m-%d")
    return {
        "asOf": dates[-1].strftime("%Y-%m-%d"), "nextRebalance": nxt, "companies": out,
        "rules": {"minFunds": MIN_FUNDS, "maxFunds": MAX_FUNDS, "minW": MIN_W, "maxW": MAX_W,
                  "minHistoryDays": MIN_HISTORY, "minAum": MIN_AUM, "minInvestors": MIN_INVESTORS,
                  "minVol": MIN_VOL, "excludedCategories": sorted(EXCLUDED_CATEGORIES), "okGrades": OK_GRADES,
                  "maxCorr": MAX_CORR, "perCat": PER_CAT, "max1y": MAX_1Y, "stayBonus": STAY_BONUS,
                  "periodMonths": PERIOD_MONTHS, "weights": WEIGHTS,
                  "retWindows": {k: w for k, (_, w) in RET_WINDOWS.items()}},
    }

"""BES (bireysel emeklilik) fonları: sınıflama, skorlama ve uzun vadeli model.

Yatırım fonlarından farkları
----------------------------
* Fon kendi emeklilik şirketinle yaptığın sözleşme içinden alınır; BEFAS (Temmuz 2021)
  sayesinde başka şirketlerin fonları da bu sözleşmeden alınabilir (grup, "yabancı"
  ibareli, para piyasası, katkı ve başlangıç fonları hariç). Model bu yüzden tüm
  şirketlerin BEFAS'a açık fonlarından tek sepet kurar.
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


# BEFAS'ta (başka şirketin sözleşmesinden) alınamayan fonlar — EGM: grup fonları, unvanında
# "yabancı" ibaresi olan fonlar, para piyasası, katkı ve başlangıç fonları. OKS fonları
# yalnızca otomatik katılım sözleşmesine açıktır.
def befas_status(name: str, category: str, access: str) -> str | None:
    """BEFAS'tan alınamıyorsa nedeni; alınabiliyorsa None."""
    text = (name or "").upper()
    if access == "GRUP":
        return "grup fonu"
    if access == "DK":
        return "devlet katkısı fonu"
    if access == "OKS":
        return "OKS fonu"
    if re.search(r"YABANCI", text):
        return "unvanında 'yabancı' ibaresi var"
    if category == "Para Piyasası":
        return "para piyasası fonu"
    if category == "Başlangıç":
        return "başlangıç fonu"
    return None


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
    funds["befas_no"] = [befas_status(n, c, a) for n, c, a in zip(funds["name"], funds["category"], funds["access"])]
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

MIN_FUNDS, MAX_FUNDS = 1, 6                 # alt sınır yok, en fazla 6 fon
MIN_W, MAX_W, STEP = 0.10, 0.40, 0.05   # BES dağılımında fon başına %10'un altı pratik değil
MIN_HISTORY = 504                        # 2 yıl (geçmiş test 2023 sonundan başlar; TÜFE şartı 3 yılı ayrıca ister)
MIN_AUM, MIN_INVESTORS = 50e6, 1000
MIN_VOL = 0.06                           # PPF benzeri (para piyasası, kısa vade) fon alınmaz
EXCLUDED_CATEGORIES = {"Para Piyasası", "Borçlanma Araçları", "Standart", "Başlangıç",
                       "Devlet Katkısı", "OKS", "Grup"}
OK_GRADES = ("A+", "A", "B")
MAX_CORR = 0.85
PER_CAT = 2
PER_COMPANY = 2                          # BEFAS sepetinde aynı emeklilik şirketinden en fazla
WEIGHT_MODE = "equal"                    # 1/N: tahmin hatasına en dayanıklı (DeMiguel vd. 2009)
MAX_1Y = 2.0
# Stratejik (varlık sınıfı) seçim: Türkiye BES fonlarında performans kalıcılığı zayıf
# (Özkan ve Öztürk 2021; Kuzubaş vd. 2019); kalıcı olan yalnızca en kötü fonların kötü
# kalması (Carhart 1997). Bu yüzden önce varlık sınıfı dağılımı kurulur, sınıf içinde
# zayıf fonlar elenir ve kalan en sağlam fonlar alınır.
# Kurulum günü engelleyen risk bayrakları. Yatırım fonu skorlamasındaki "kuyruk riski" ve
# "getiri anomalisi" kısa vadeli ölçülerdir; altın ve teknoloji gibi uzun vadede güçlü sınıfları
# da sık işaretler. Kurucu riski her zaman engeller.
BES_FLAGS = ("flag_tail", "flag_hot", "founder_risk", "anomaly")
# Vergi yerleşimi: normal fonda %17,5 stopajlı (altın, teknoloji/yabancı, çok varlıklı) sınıflar BES'te
# vergi avantajı taşır; yerli hisse yoğun fonlar normal fonda zaten %0. Bu sınıflara puan eklenir.
TAX_TILT = 5.0
BES_TREND = False
TAX_ADV_BUCKETS = ("Altın / kıymetli maden", "Teknoloji / yabancı", "Çok varlıklı")
SELECT_MODE = "score"                    # "score" (puan sırası) | "strategic" (varlık sınıfı eşit) — 2 ayrı testte "score" daha iyi
BUCKET_WEIGHT = "equal"                  # varlık sınıfları arası: "equal" | "invvol" (risk paritesi)
PER_BUCKET = 2                           # sınıf başına fon
LOSER_CUT = 0.30                         # sınıf içinde reel getiri / Sharpe'ta alt %30 elenir
TREND_FILTER = False                     # sınıf endeksi 40 haftalık ortalamanın altındaysa payı diğerlerine
STAY_BONUS = 10.0                        # uzun vade: iyi kalan fon sepette kalsın (testte 2 yarıda da daha iyi)
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
        bad = (scores["p_anomaly"].fillna(0) > 0) if "anomaly" in BES_FLAGS else pd.Series(False, index=scores.index)
        for col in ("flag_tail", "flag_hot", "founder_risk"):
            if col in scores and col in BES_FLAGS:
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
    m["tech"] = funds["tech"].reindex(m.index)
    m["befas_no"] = funds["befas_no"].reindex(m.index)
    m["investors"] = inv.reindex(m.index)
    m["aum"] = size.reindex(m.index)
    m["quant"] = scores["score"].reindex(m.index) if scores is not None else np.nan
    m["grade"] = grades.reindex(m.index) if scores is not None else None
    m.attrs = {}
    return m, px.iloc[-253:].iloc[::5].pct_change().iloc[1:]


def bucket(row) -> str:
    """Varlık sınıfı kovası: sepette çeşitlilik bunun üzerinden sağlanır."""
    if row["category"] == "Kıymetli Madenler":
        return "Altın / kıymetli maden"
    if row.get("tech") or row.get("foreign"):
        return "Teknoloji / yabancı"
    if row["category"] == "Hisse Senedi":
        return "Yerli hisse"
    return "Çok varlıklı"


def _weights(sel: pd.DataFrame) -> pd.Series:
    if WEIGHT_MODE == "equal":
        raw = pd.Series(1.0, index=sel.index)
    elif WEIGHT_MODE == "score_invvol":   # risk paritesine yakın: oynak fon daha az pay alır
        raw = sel["score"] / sel["vol"].clip(lower=0.05)
    else:                                 # "score2_sqrtvol": puana ağırlık veren eski kural
        raw = sel["score"] ** 2 / sel["vol"].clip(lower=0.05) ** 0.5
    return _round(raw)


def _pick(m: pd.DataFrame, wk: pd.DataFrame | None, prev: list[str] | None,
          company: str | None = None, befas: bool = False) -> list[dict]:
    """company verilirse o şirketin fonları; befas=True ise tüm şirketlerin BEFAS'a açık fonları."""
    if m.empty:
        return []
    c = m[m["company"] == company].copy() if company else m[m["befas_no"].isna()].copy()
    if c.empty:
        return []
    spike = c.apply(lambda r: model._spike_reason(r, MAX_1Y), axis=1)
    tufe_ok = c["real_3y"] > 0 if c["real_3y"].notna().any() else pd.Series(True, index=c.index)
    base = c[(c["vol"] >= MIN_VOL) & spike.isna()].copy()
    if BES_TREND:  # deneme: 200 günlük ortalamanın altındaki ya da 6 ayda PPF gerisindeki fon alınmaz
        base = base[(base["sma_gap"].fillna(0) > 0) & (base["mom6x"].fillna(0) > 0)]
    if base.empty:
        return []
    base["score"] = _score(base)
    if prev:
        base.loc[base.index.isin(prev), "score"] += STAY_BONUS
    base["fill"] = False
    base["bucket"] = base.apply(bucket, axis=1)
    if TAX_TILT:
        base.loc[base["bucket"].isin(TAX_ADV_BUCKETS), "score"] += TAX_TILT
    pool = base[tufe_ok.reindex(base.index).fillna(False)].copy()
    # TÜFE'yi geçen fon 3'ten azsa: geçemeyenlerden TÜFE'ye en yakın olanlarla tamamla (işaretli)
    if len(pool) < MIN_FUNDS:
        extra = base[~base.index.isin(pool.index)].sort_values(["real_3y", "score"], ascending=False)
        extra = extra.head(MIN_FUNDS - len(pool)).copy()
        extra["fill"] = True
        extra["score"] = extra["score"] * 0.9
        pool = pd.concat([pool, extra])
        pool.attrs = {}
    group = "bucket" if befas else "category"
    chosen, per_grp, per_co = [], {}, {}
    for code in pool.sort_values("score", ascending=False).index:
        if len(chosen) >= MAX_FUNDS:
            break
        g, co = pool.at[code, group], pool.at[code, "company"]
        if per_grp.get(g, 0) >= PER_CAT:
            continue
        if befas and per_co.get(co, 0) >= PER_COMPANY:
            continue
        if chosen and wk[chosen].corrwith(wk[code]).max() > MAX_CORR:
            continue
        if len(chosen) >= MIN_FUNDS and pool.at[code, "score"] < 40:
            break
        chosen.append(code)
        per_grp[g] = per_grp.get(g, 0) + 1
        per_co[co] = per_co.get(co, 0) + 1
    # Az fon kaldıysa ikinci tur: korelasyon ve grup sınırı olmadan en iyi fonlarla 3'e tamamla
    if len(chosen) < MIN_FUNDS:
        for code in pool.sort_values("score", ascending=False).index:
            if len(chosen) >= MIN_FUNDS:
                break
            if code not in chosen:
                chosen.append(code)
    if not chosen:
        return []
    sel = pool.loc[chosen]
    weights = _weights(sel)
    return [{"code": k, "w": float(weights[k]), **sel.loc[k].to_dict()} for k in weights.sort_values(ascending=False).index]


def _pick_strategic(m: pd.DataFrame, wk: pd.DataFrame | None, prev: list[str] | None) -> list[dict]:
    """BEFAS'a açık fonlardan varlık sınıfı temelli sepet."""
    if m.empty:
        return []
    c = m[m["befas_no"].isna()].copy()
    spike = c.apply(lambda r: model._spike_reason(r, MAX_1Y), axis=1) if len(c) else pd.Series(dtype=object)
    base = c[(c["vol"] >= MIN_VOL) & spike.isna()].copy()
    if base.empty:
        return []
    base["score"] = _score(base)
    if prev:
        base.loc[base.index.isin(prev), "score"] += STAY_BONUS
    base["fill"] = False
    base["bucket"] = base.apply(bucket, axis=1)
    picks, bucket_of = [], {}
    per_co = {}
    for bk, g in base.groupby("bucket"):
        g = g.copy()
        # Kaybedenleri ele: reel 3Y getiri ve Sharpe'ın ortalama yüzdeliğinde alt dilim
        rank = (g["real_3y"].rank(pct=True).fillna(0.5) + g["sharpe"].rank(pct=True).fillna(0.5)) / 2
        keep = g[rank > LOSER_CUT] if len(g) >= 4 else g
        chosen = []
        for code in keep.sort_values("score", ascending=False).index:
            if len(chosen) >= PER_BUCKET:
                break
            co = keep.at[code, "company"]
            if per_co.get(co, 0) >= PER_COMPANY:
                continue
            peers = [x for x in (*picks, *chosen) if x in wk.columns]
            if peers and wk[peers].corrwith(wk[code]).max() > MAX_CORR:
                continue
            chosen.append(code)
            per_co[co] = per_co.get(co, 0) + 1
        for code in chosen:
            bucket_of[code] = bk
        picks += chosen
    if not picks:
        return []
    sel = base.loc[picks]
    buckets = sorted(set(bucket_of.values()))
    if BUCKET_WEIGHT == "invvol":
        bw = pd.Series({b: 1 / max(sel.loc[[k for k, v in bucket_of.items() if v == b], "vol"].mean(), 0.05) for b in buckets})
    else:
        bw = pd.Series(1.0, index=buckets)
    if TREND_FILTER and wk is not None:
        for b in buckets:
            codes = [k for k, v in bucket_of.items() if v == b and k in wk.columns]
            idx = (1 + wk[codes].mean(axis=1).fillna(0)).cumprod()
            if len(idx) >= 40 and idx.iloc[-1] < idx.iloc[-40:].mean():
                bw[b] *= 0.25  # düşüş trendindeki sınıfın payı dörtte bire iner, kalan diğerlerine
    bw = bw / bw.sum()
    raw = pd.Series({k: bw[bucket_of[k]] / sum(1 for v in bucket_of.values() if v == bucket_of[k]) for k in picks})
    weights = _round(raw)
    return [{"code": k, "w": float(weights[k]), **sel.loc[k].to_dict()} for k in weights.sort_values(ascending=False).index]


def _universe_pool(m: pd.DataFrame) -> list[str]:
    """Kıyas evreni: BEFAS'a açık, uzun vadeye uygun (oynaklık ≥ sınır, sıçramasız) tüm fonlar."""
    if m.empty:
        return []
    c = m[m["befas_no"].isna() & (m["vol"] >= MIN_VOL)]
    spike = c.apply(lambda r: model._spike_reason(r, MAX_1Y), axis=1) if len(c) else pd.Series(dtype=object)
    return list(c.index[spike.isna()]) if len(c) else []


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
    companies: list[str] = []  # şirket içi sepetler kaldırıldı; model BEFAS geneli kurulur
    BEFAS = "__befas__"
    history = {c: [] for c in [*companies, BEFAS]}
    unis, univ_codes = {}, {}
    for i in forms:
        unis[i], wk = _universe(price, panel, funds, rf_idx, tufe, i, scores_at.get(i))
        univ_codes[i] = _universe_pool(unis[i])
        for comp in [*companies, BEFAS]:
            prev = [f["code"] for f in history[comp][-1]["funds"]] if history[comp] else None
            funds_i = ((_pick_strategic(unis[i], wk, prev) if SELECT_MODE == "strategic" else _pick(unis[i], wk, prev, befas=True)) if comp == BEFAS
                       else _pick(unis[i], wk, prev, company=comp))
            history[comp].append({"i": i, "funds": funds_i})

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

    def held(ws_list):
        """Dönem dönem ağırlık listesinden (T+1 alış, sonraki kuruluma kadar) seviye serisi."""
        rets, points = [], []
        for k, (i, ws) in enumerate(ws_list):
            a = dates[i + 1]
            e = dates[ws_list[k + 1][0] + 1] if k + 1 < len(ws_list) else dates[-1]
            if e <= a or ws is None or ws.empty:
                continue
            r = (px.loc[e, ws.index] / px.loc[a, ws.index] - 1).clip(-0.95, 5).fillna(0)
            if not points:
                points.append(a)
            rets.append(float((r * ws).sum()))
            points.append(e)
        return rets, points

    # Kıyas evreni: her dönem BEFAS'a açık, uzun vadeye uygun tüm fonlar eşit ağırlık
    univ_ws = [(i, pd.Series(1 / len(univ_codes[i]), index=univ_codes[i]) if univ_codes[i] else None) for i in forms]

    out = {}
    for comp in [*companies, BEFAS]:
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
                "co": funds.at[code, "company"], "bk": f.get("bucket"), "bf": funds.at[code, "befas_no"],
                "score": round(float(f["score"]), 1), "g": f.get("grade"),
                "gNow": scored.at[code, "grade"] if code in scored.index else None,
                "fx": bool(f.get("foreign")), "tk": bool(funds.at[code, "tech"]), "fill": bool(f.get("fill")),
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

        # Geçmiş: her dönem T+1 alış, bir sonraki kuruluma kadar tutuş; boş dönemde uygun fonlar eşit ağırlık
        items, ws_list = [], []
        for h in hist:
            items.append({"date": dates[h["i"]].strftime("%Y-%m-%d"),
                          "items": [[f["code"], round(f["w"] * 100)] for f in h["funds"]]})
            if h["funds"]:
                ws = pd.Series({f["code"]: f["w"] for f in h["funds"]})
            else:
                u = unis[h["i"]]
                codes = (univ_codes[h["i"]] if comp == BEFAS
                         else list(u.index[u["company"] == comp]) if not u.empty else [])
                ws = pd.Series(1 / len(codes), index=codes) if codes else None
            ws_list.append((h["i"], ws))
        rets, points = held(ws_list)
        backtest_out = {"available": False}
        if len(rets) >= 2:
            rs = pd.Series(rets, index=points[1:])
            lvl = pd.concat([pd.Series([100.0], index=[points[0]]), (1 + rs).cumprod() * 100])
            series, stats = {"model": [round(float(x), 3) for x in lvl.values]}, {}
            stats["model"] = _stats(lvl, rs, None)
            # Evren: aynı tarihlerde BEFAS'a açık uygun fonların eşit ağırlıklı sepeti
            u_r, u_p = held(univ_ws)
            if len(u_r) >= 2:
                us = pd.Series(u_r, index=u_p[1:])
                ul = pd.concat([pd.Series([100.0], index=[u_p[0]]), (1 + us).cumprod() * 100]).reindex(points).ffill()
                ul = ul / ul.iloc[0] * 100
                series["universe"] = [None if pd.isna(x) else round(float(x), 3) for x in ul.values]
                stats["universe"] = _stats(ul, ul.pct_change().dropna(), None)
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
            "company": "BEFAS (tüm şirketler)" if comp == BEFAS else comp,
            "channel": None if comp == BEFAS else (funds.loc[funds["company"] == comp, "channel"].dropna().iloc[0]
                                                   if funds.loc[funds["company"] == comp, "channel"].notna().any() else None),
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
        "asOf": dates[-1].strftime("%Y-%m-%d"), "nextRebalance": nxt,
        "befas": out.pop(BEFAS, None), "companies": out,
        "rules": {"minFunds": MIN_FUNDS, "maxFunds": MAX_FUNDS, "minW": MIN_W, "maxW": MAX_W,
                  "minHistoryDays": MIN_HISTORY, "minAum": MIN_AUM, "minInvestors": MIN_INVESTORS,
                  "minVol": MIN_VOL, "excludedCategories": sorted(EXCLUDED_CATEGORIES), "okGrades": OK_GRADES,
                  "maxCorr": MAX_CORR, "perCat": PER_CAT, "max1y": MAX_1Y, "stayBonus": STAY_BONUS,
                  "periodMonths": PERIOD_MONTHS, "weights": WEIGHTS, "perCompany": PER_COMPANY,
                  "taxTilt": TAX_TILT, "taxBuckets": list(TAX_ADV_BUCKETS),
                  "weightMode": WEIGHT_MODE,
                  "retWindows": {k: w for k, (_, w) in RET_WINDOWS.items()}},
    }

"""TEFAS Quant puanlama ve cezalandırma motoru.

Adımlar
-------
1. Son HISTORY_YEARS yılın fiyat / pay / yatırımcı / büyüklük panelini yükle.
2. Fiyatı bayatlamış (askıdaki, tasfiyedeki) fonları dışla.
3. Her fon için getiri, risk ve akış metriklerini hesapla.
4. Kategori içinde 5 bileşen skoru üret: performans, risk, yatırımcı/akış,
   maliyet, portföy kalitesi -> ağırlıklı mutlak skor.
5. Cezalar ve ayarlar: az yatırımcı, net nakit çıkışı, getiri anomalisi,
   veri güveni, yatırımcı istikrarı.
6. Kategori içi sıra ve göreli not (A+ ... D).
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3

import numpy as np
import pandas as pd

from . import config
from .categorize import categorize

TRADING_DAYS = 252
MIN_HISTORY_FOR_GRADES = 63  # not üretmek için evrende gereken işlem günü
QUALIFIED_RE = re.compile(r"SERBEST|N[İI]TEL[İI]KL[İI]|G[İI]R[İI][ŞS][İI]M SERMAYES[İI]|GAYR[İI]MENKUL")


# =================================================================== veri

def load_panel(conn: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    df = pd.read_sql("SELECT date, code, price, shares, investors, size FROM prices", conn)
    df["date"] = pd.to_datetime(df["date"])
    panel = {
        col: df.pivot(index="date", columns="code", values=col).sort_index()
        for col in ("price", "shares", "investors", "size")
    }
    panel["splits"] = adjust_splits(panel)
    return panel


def adjust_splits(panel: dict[str, pd.DataFrame]) -> list[dict]:
    """Pay bölünmesi / birleşmesini geriye dönük düzeltir (yerinde).

    Bölünmede fon büyüklüğü değişmez; fiyat 10'un bir kuvvetine bölünür, pay
    adedi aynı oranda artar (ör. İş Portföy TI2: 1003,6 -> 0,102, pay ×10.000).
    Düzeltilmezse -%99,99 sahte getiri oluşur. Gerçek çöküşte (ör. Pardus,
    Ekim 2026) pay adedi değişmez, büyüklük de çöker: o durum düzeltilmez.
    """
    price, shares, size = panel["price"], panel["shares"], panel["size"]
    ratio = price / price.shift(1)
    candidates = ratio.stack()
    candidates = candidates[(candidates < 0.2) | (candidates > 5)]
    splits = []
    for (day, code), r in candidates.items():
        i = price.index.get_loc(day)
        k = 10 ** round(np.log10(1 / r))           # bölünme oranı: 10, 100, 1000, ...
        if abs(np.log10(1 / r) - np.log10(k)) > 0.05:
            continue
        sh_ratio = shares[code].iloc[i] / shares[code].iloc[i - 1]
        size_ratio = size[code].iloc[i] / size[code].iloc[i - 1]
        if not (0.7 < sh_ratio / k < 1.3 and 0.8 < size_ratio < 1.25):
            continue
        before = price.index[:i]
        price.loc[before, code] = price.loc[before, code] / k
        shares.loc[before, code] = shares.loc[before, code] * k
        splits.append({"code": code, "date": day.strftime("%Y-%m-%d"), "factor": k})
    return splits


# TEFAS'ın "Serbest" şemsiyesi para piyasasından hisseye her stratejiyi tek
# kovada topluyor (~1.200 fon). Adil kıyas için ünvandan alt sınıf çıkarılır.
SERBEST_SUBTYPES = [
    ("Para Piyasası", re.compile(r"PARA P[İI]YASASI|KISA VADEL[İI]|L[İI]K[İI]T")),
    ("Döviz", re.compile(r"D[ÖO]V[İI]Z|EUROBOND|DOLAR|USD|EURO|YABANCI PARA")),
    ("Kıymetli Madenler", re.compile(r"ALTIN|G[ÜU]M[ÜU][ŞS]|KIYMETL[İI]")),
    ("Hisse Senedi", re.compile(r"H[İI]SSE")),
    ("Katılım", re.compile(r"KATILIM|K[İI]RA SERT")),
    ("Fon Sepeti", re.compile(r"FON SEPET[İI]")),
]


def refine_category(category: str, name: str) -> str:
    if category != "Serbest":
        return category
    text = (name or "").upper()
    for label, pattern in SERBEST_SUBTYPES:
        if pattern.search(text):
            return f"Serbest · {label}"
    return "Serbest · Çoklu Varlık"


FOUNDER_RE = re.compile(r"^(.*?\b(?:PORTFÖY|PORTFOY|PYŞ|PYS)\b)", re.IGNORECASE)


def founder_of(name) -> str:
    """Ünvandan portföy şirketi: "PARDUS PORTFÖY İKİNCİ ..." -> "PARDUS PORTFÖY"."""
    text = str(name or "").upper().strip()
    m = FOUNDER_RE.match(text)
    if not m:
        return " ".join(text.split()[:2])
    return m.group(1).replace("PYŞ", "PORTFÖY").replace("PYS", "PORTFÖY").replace("PORTFOY", "PORTFÖY").strip()


def load_funds(conn: sqlite3.Connection) -> pd.DataFrame:
    funds = pd.read_sql(
        "SELECT code, name, category, category_src, fee, stopaj, trading_active, is_serbest FROM funds",
        conn,
    ).set_index("code")
    # FVT'de 0 görünen ücret çoğunlukla eksik veri; "en ucuz" sayılmasın
    funds.loc[funds["fee"] <= 0, "fee"] = np.nan
    funds["category"] = funds["category"].fillna(funds["name"].map(categorize))
    # Özel fon: tek / birkaç yatırımcıya kurulmuş, halka açık değil
    funds["private"] = funds["name"].fillna("").str.upper().str.contains("ÖZEL FON", regex=False)
    funds["founder"] = funds["name"].map(founder_of)
    is_serbest_cat = funds["category"] == "Serbest"
    funds["category"] = [refine_category(c, n) for c, n in zip(funds["category"], funds["name"])]
    name_upper = funds["name"].fillna("").str.upper().str.replace("ÖZEL SEKTÖR", "", regex=False)
    funds["qualified"] = (
        (funds["is_serbest"] == 1)
        | is_serbest_cat
        | name_upper.str.contains(QUALIFIED_RE)
    ).astype(int)
    return funds


# ================================================================ metrikler

def _trailing_return(prices: pd.DataFrame, n: int) -> pd.Series:
    """Son fiyatın n işlem günü önceki fiyata göre getirisi (%)."""
    if len(prices) <= n:
        return pd.Series(np.nan, index=prices.columns)
    return (prices.iloc[-1] / prices.iloc[-1 - n] - 1) * 100


def compute_metrics(panel: dict[str, pd.DataFrame], funds: pd.DataFrame,
                    light: bool = False) -> tuple[pd.DataFrame, list, float]:
    """light=True: skorda kullanılmayan beta/alfa/bilgi oranı atlanır (backtest hızı)."""
    price = panel["price"]
    universe_last = price.index[-1]
    last_seen = price.apply(pd.Series.last_valid_index)
    first_seen = price.apply(pd.Series.first_valid_index)
    n_obs = price.notna().sum()

    # ---- dışlananlar
    stale_cutoff = universe_last - pd.Timedelta(days=config.STALE_PRICE_DAYS)
    # Son 3 ayda tepeden bugüne kayıp (bölünmeler düzeltildikten sonra)
    recent = price.iloc[-63:].ffill()
    recent_loss = 1 - recent.iloc[-1] / recent.max()
    size_recent = panel["size"].iloc[-63:].ffill()
    size_loss = 1 - size_recent.iloc[-1] / size_recent.max()
    # Pay adedi ve yatırımcı sayısı son 10 işlem gününde hiç değişmemiş ama önceki
    # 50 günde hareketliyse alım-satım fiilen durmuştur. FVT'nin işlem bayrağı
    # gecikebildiği için (Ekim 2026'da Pardus/Hedef/Atlas/Bulls fonları "işlemde"
    # görünüyordu) bu kural bayraktan bağımsız uygulanır.
    sh = panel["shares"].ffill()
    inv_all = panel["investors"].ffill()
    frozen = ((sh.iloc[-10:].nunique() <= 1) & (sh.iloc[-60:-10].nunique() > 1)
              & (inv_all.iloc[-10:].nunique() <= 1))
    excluded = []
    keep = []
    private_skipped = 0
    for code in price.columns:
        known = code in funds.index
        name = funds.at[code, "name"] if known else code
        halted = known and funds.at[code, "trading_active"] == 0
        if known and funds.at[code, "private"]:
            private_skipped += 1
            continue
        if last_seen[code] < stale_cutoff:
            excluded.append({
                "code": code, "name": name, "lastDate": last_seen[code].strftime("%Y-%m-%d"),
                "reason": "TEFAS işlemi durdurulmuş" if halted else "Fiyat yayımlanmıyor",
            })
        elif (halted and (recent_loss.get(code, 0) > 0.5 or size_loss.get(code, 0) > 0.9)) or frozen.get(code, False):
            # İşleme kapalı fonlar (ör. SPK kararıyla durdurulan Pardus/A1 Capital, Ekim 2026):
            # alınıp satılamadığı için sıralamaya alınmaz ama nedeniyle listede görünür.
            if halted and recent_loss.get(code, 0) > 0.5:
                reason = f"İşlemleri durdurulmuş, son 3 ayda %{recent_loss[code] * 100:.0f} değer kaybı"
            elif halted and size_loss.get(code, 0) > 0.9:
                reason = f"İşlemleri durdurulmuş, büyüklük son 3 ayda %{size_loss[code] * 100:.0f} eridi"
            else:
                reason = "Pay adedi ve yatırımcı sayısı 10 gündür değişmiyor (alım-satım durmuş olabilir)"
            excluded.append({
                "code": code, "name": name, "lastDate": last_seen[code].strftime("%Y-%m-%d"),
                "reason": reason,
            })
        elif n_obs[code] >= config.MIN_HISTORY_DAYS:
            keep.append(code)

    # Kısa tatilleri doldur (fon bazlı tatil / geç yayın), uzun boşlukları değil
    px = price[keep].ffill(limit=5)
    rets = price[keep].pct_change(fill_method=None).clip(-0.5, 1.0)
    category = funds["category"].reindex(keep).fillna("Diğer")

    m = pd.DataFrame(index=keep)
    m["category"] = category
    m.attrs["private_skipped"] = private_skipped

    # ---- getiriler
    # Ekranda gösterilen: yeterli geçmiş yoksa boş
    for label, n in config.DISPLAY_WINDOWS.items():
        m[f"raw_r_{label}"] = _trailing_return(px, n)
    # Skorda kullanılan: eksik uzun dönem bir kısa dönemle doldurulur
    prev = None
    for label, (n, _w) in config.PERFORMANCE_WINDOWS.items():
        r = _trailing_return(px, n)
        if prev is not None:
            r = r.fillna(m[prev])
        m[f"r_{label}"] = r
        prev = f"r_{label}"
    m["r_1g"] = (px.iloc[-1] / px.iloc[-2] - 1) * 100

    # ---- risksiz faiz: para piyasası fonlarının günlük medyan getirisi
    mm_cols = category[category == "Para Piyasası"].index
    mm = rets[mm_cols]
    rf_daily = mm.median(axis=1)[mm.notna().sum(axis=1) >= 5].clip(-0.01, 0.01)
    if config.RISK_FREE_RATE is not None or rf_daily.empty:
        const = config.RISK_FREE_RATE if config.RISK_FREE_RATE is not None else config.RISK_FREE_FALLBACK
        rf_daily = pd.Series(const / TRADING_DAYS, index=rets.index)
    rf_daily = rf_daily.reindex(rets.index).ffill().bfill()
    rf_current = float(rf_daily.iloc[-TRADING_DAYS:].mean() * TRADING_DAYS)

    # ---- risk: son RISK_WINDOW_DAYS işlem günü (v2 testindeki pencere)
    w = config.RISK_WINDOW_DAYS
    r_win = rets.iloc[-w:]
    excess = r_win.sub(rf_daily.iloc[-w:], axis=0)
    vol = r_win.std() * np.sqrt(TRADING_DAYS)
    m["volatility"] = vol
    m["sharpe"] = (excess.mean() * TRADING_DAYS) / vol.replace(0, np.nan)
    downside = excess.where(excess < 0).std() * np.sqrt(TRADING_DAYS)
    m["sortino"] = (excess.mean() * TRADING_DAYS) / downside.replace(0, np.nan)
    px_win = px.iloc[-(w + 1):]
    m["mdd"] = 1 - (px_win / px_win.cummax()).min()
    # Pürüzsüzlük: günlük getirilerin 1. derece otokorelasyonu (Getmansky-Lo-Makarov).
    # Değerlemesi zor / likit olmayan varlık taşıyan fonlarda yüksek çıkar.
    m["smoothness"] = r_win.apply(lambda s: s.autocorr(1) if s.notna().sum() > 30 else np.nan)

    obs = rets.notna().sum()
    first_px = px.apply(lambda s: s.dropna().iloc[0])
    m["cagr"] = (px.iloc[-1] / first_px) ** (TRADING_DAYS / obs.clip(lower=1)) - 1
    m["calmar"] = (m["r_1y"] / 100 / m["mdd"].replace(0, np.nan)).clip(-10, 10)

    # ---- kategori benchmark'ı: eşit ağırlıklı günlük getiri
    beta, alpha, info = {}, {}, {}
    for cat, codes in ({} if light else category.groupby(category).groups).items():
        bench = rets[list(codes)].mean(axis=1)
        for code in codes:
            pair = pd.concat([rets[code], bench, rf_daily], axis=1, keys=["f", "b", "rf"]).dropna()
            if len(pair) < 30 or pair["b"].var() == 0:
                beta[code], alpha[code], info[code] = 1.0, 0.0, 0.0
                continue
            b = pair["f"].cov(pair["b"]) / pair["b"].var()
            beta[code] = b
            alpha[code] = ((pair["f"] - pair["rf"]).mean() - b * (pair["b"] - pair["rf"]).mean()) * TRADING_DAYS
            active = pair["f"] - pair["b"]
            te = active.std() * np.sqrt(TRADING_DAYS)
            info[code] = (active.mean() * TRADING_DAYS / te) if te > 0 else 0.0
    m["beta"], m["alpha"], m["information_ratio"] = pd.Series(beta), pd.Series(alpha), pd.Series(info)

    # ---- yatırımcı, büyüklük, akış (TEFAS pay adedi değişimi x fiyat)
    inv = panel["investors"][keep].ffill(limit=5)
    size = panel["size"][keep].ffill(limit=5)
    shares = panel["shares"][keep].ffill(limit=5)
    m["investors"] = inv.iloc[-1]
    m["aum"] = size.iloc[-1]
    m["investor_growth_1m"] = (inv.iloc[-1] / inv.iloc[-22] - 1) * 100 if len(inv) > 22 else np.nan
    m["aum_growth_1m"] = (size.iloc[-1] / size.iloc[-22] - 1) * 100 if len(size) > 22 else np.nan
    flow = shares.diff() * px
    m["flow_1w"] = flow.iloc[-5:].sum(min_count=1)
    m["flow_1m"] = flow.iloc[-21:].sum(min_count=1)
    m["flow_3m"] = flow.iloc[-63:].sum(min_count=1)
    weighted = m["flow_3m"].fillna(0) * 0.6 + m["flow_1m"].fillna(0) * 0.3 + m["flow_1w"].fillna(0) * 0.1
    m["flow_ratio"] = (weighted / m["aum"].replace(0, np.nan) * 100).clip(-100, 100)
    m["flow_3m_ratio"] = (m["flow_3m"] / m["aum"].replace(0, np.nan) * 100).clip(-100, 100)

    # ---- maliyet
    fee = funds["fee"].reindex(keep)
    m["fee"] = fee.fillna(fee.groupby(category).transform("median")).fillna(fee.median())
    m["stopaj"] = funds["stopaj"].reindex(keep)

    # ---- veri güveni (0-100)
    days_since = (universe_last - last_seen[keep]).dt.days
    span_days = price.index.get_indexer(last_seen[keep]) - price.index.get_indexer(first_seen[keep]) + 1
    density = (n_obs[keep] / pd.Series(span_days, index=keep)).clip(upper=1) * 100
    age = (n_obs[keep] / (config.HISTORY_YEARS * TRADING_DAYS) * 100).clip(upper=100)
    recency = np.where(days_since <= 3, 100, np.maximum(100 - days_since * 5, 10))
    maturity = pd.cut(n_obs[keep], [-1, 20, 62, 125, 251, 10**6], labels=[10, 25, 50, 75, 100]).astype(float)
    m["confidence"] = (age * 0.35 + density * 0.25 + recency * 0.20 + maturity * 0.20).round(1)
    m["history_days"] = n_obs[keep]
    m["first_date"] = first_seen[keep].dt.strftime("%Y-%m-%d")

    return m, excluded, rf_current


# ================================================================== skorlar

def _pct_rank(s: pd.Series) -> pd.Series:
    """Kategori içi yüzdelik (0-100]; eksik değer kategori medyanı sayılır.

    Kategoride hiç değer yoksa (ör. FVT'ye ulaşılamadı, ücret yok) herkes nötr 50 alır.
    """
    s = pd.to_numeric(s, errors="coerce")
    if s.notna().sum() == 0:
        return pd.Series(50.0, index=s.index)
    return s.fillna(s.median()).rank(pct=True) * 100


def performance_score(g: pd.DataFrame) -> pd.Series:
    total = sum(w for _, w in config.PERFORMANCE_WINDOWS.values())
    return sum(_pct_rank(g[f"r_{k}"]) * w for k, (_, w) in config.PERFORMANCE_WINDOWS.items()) / total


def risk_score(g: pd.DataFrame) -> pd.Series:
    """Sharpe, maksimum düşüş, Sortino, pürüzsüzlük — kategori içi yüzdelik."""
    total = sum(w for w, _ in config.RISK_METRICS.values())
    parts = []
    for key, (w, higher_better) in config.RISK_METRICS.items():
        pct = _pct_rank(g[key])
        parts.append((pct if higher_better else 100 - pct + 100 / len(g)) * w)
    return sum(parts) / total


def investor_score(g: pd.DataFrame) -> pd.Series:
    """Büyüklük değişimi ve net akış — kategori içi yüzdelik."""
    total = sum(config.INVESTOR_METRICS.values())
    return sum(_pct_rank(g[k]) * w for k, w in config.INVESTOR_METRICS.items()) / total


def cost_score(g: pd.DataFrame) -> pd.Series:
    """Yönetim ücreti: kategorideki en ucuz fon ~100, en pahalı ~0."""
    if g["fee"].notna().sum() == 0:
        return pd.Series(50.0, index=g.index)
    return 100 - _pct_rank(g["fee"]) + 100 / len(g)


def portfolio_score(g: pd.DataFrame) -> pd.Series:
    """Fon büyüklüğü (kategori içi yüzdelik)."""
    return _pct_rank(g["aum"])


def anomaly_penalty(g: pd.DataFrame) -> pd.Series:
    if len(g) < config.MIN_CATEGORY_SIZE:
        return pd.Series(0.0, index=g.index)
    r = g["r_1y"]
    iqr = r.quantile(0.75) - r.quantile(0.25)
    z = (r - r.median()) / max(iqr, 1e-6)
    return ((z - config.ANOMALY_Z_THRESHOLD).clip(lower=0) * config.ANOMALY_PENALTY_PER_Z).clip(
        upper=config.ANOMALY_MAX_PENALTY
    ).fillna(0)


def investor_penalty(n) -> float:
    if pd.isna(n):
        return 5.0
    for limit, pts in config.INVESTOR_PENALTIES:
        if n < limit:
            return float(pts)
    return 0.0


def outflow_penalty(ratio) -> float:
    if pd.isna(ratio):
        return 0.0
    for limit, pts in config.OUTFLOW_PENALTIES:
        if ratio < limit:
            return float(pts)
    return 0.0


def stability_adjustment(n) -> float:
    if pd.isna(n):
        return 0.0
    for limit, pts in [(100, -5), (500, -3), (1000, -1), (2000, 0), (5000, 1), (10000, 2)]:
        if n < limit:
            return float(pts)
    return 3.0


def rating(percentile: float, score: float, category_size: int) -> tuple[str, str]:
    """Göreli mod: kategori içi dağılım (%10 / %22.5 / %35 / %22.5 / %10).
    Küçük kategorilerde ya da "absolute" modda sabit skor eşikleri."""
    if config.RATING_MODE == "relative" and category_size >= config.MIN_CATEGORY_SIZE:
        value, bands = percentile, [(90, "A+", "GÜÇLÜ AL"), (67.5, "A", "AL"), (32.5, "B", "İZLE"), (10, "C", "ZAYIF")]
    else:
        value, bands = score, [(85, "A+", "GÜÇLÜ AL"), (75, "A", "AL"), (65, "B", "İZLE"), (55, "C", "ZAYIF")]
    for limit, grade, signal in bands:
        if value > limit:
            return grade, signal
    return "D", "UZAK DUR"


def founder_risk(funds: pd.DataFrame, scored_codes, excluded: list) -> dict:
    """Halka açık fonlarının en az %30'u (en az 3) sorunlu olan portföy şirketleri.

    Sorunlu: işleme kapalı, çökmüş, alım-satımı donmuş ya da fiyatı durmuş (dışlanan).
    """
    cfg = config.FOUNDER_RISK
    bad = {x["code"] for x in excluded}
    public = set(scored_codes) | bad
    founder = funds["founder"].reindex(list(public))
    out = {}
    for name, codes in founder.groupby(founder).groups.items():
        k = sum(c in bad for c in codes)
        if k >= cfg["min_funds"] and k / len(codes) >= cfg["min_share"]:
            out[name] = {"problem": int(k), "total": int(len(codes))}
    return out


def score_funds(m: pd.DataFrame, founder_flag: pd.Series | None = None,
                prev_grades: list[pd.Series] | None = None) -> pd.DataFrame:
    """founder_flag: kurucu riski taşıyan fonlar (True); prev_grades: önceki ay
    sonlarının temel notları (süreklilik şartı için). İkisi de verilmezse
    yalnızca temel (göreli) notlar üretilir."""
    parts = []
    for _cat, g in m.groupby("category"):
        g = g.copy()
        g["s_performance"] = performance_score(g)
        g["s_risk"] = risk_score(g)
        g["s_investor"] = investor_score(g)
        g["s_cost"] = cost_score(g)
        g["s_portfolio"] = portfolio_score(g)
        g["p_anomaly"] = anomaly_penalty(g)
        parts.append(g)
    s = pd.concat(parts)

    w = config.COMPONENT_WEIGHTS
    s["absolute"] = sum(s[f"s_{k}"] * v for k, v in w.items())
    s["p_investor"] = s["investors"].map(investor_penalty)
    s["p_outflow"] = s["flow_ratio"].map(outflow_penalty) * 0.5
    s["adj_confidence"] = (s["confidence"] / 100 - 0.5) * 10
    s["adj_stability"] = s["investors"].map(stability_adjustment)
    s["score"] = (
        s["absolute"] - s["p_investor"] - s["p_outflow"] - s["p_anomaly"]
        + s["adj_confidence"] + s["adj_stability"]
    ).clip(0, 100)
    # Hesaplanamayan skor (eksik veri) nötr 50 sayılır; iş çökmesin, fon listeden düşmesin
    s["score"] = s["score"].fillna(50.0)
    flag = (founder_flag.reindex(s.index).fillna(False).astype(bool)
            if founder_flag is not None else pd.Series(False, index=s.index))
    s["founder_risk"] = flag
    s["p_founder"] = np.where(flag, config.FOUNDER_RISK["penalty"], 0.0)
    s["score"] = (s["score"] - s["p_founder"]).clip(0, 100)

    s["rank"] = s.groupby("category")["score"].rank(ascending=False, method="min").astype(int)
    s["cat_size"] = s.groupby("category")["score"].transform("count").astype(int)
    s["percentile"] = (s["cat_size"] - s["rank"] + 1) / s["cat_size"] * 100
    graded = [rating(p, sc, n) for p, sc, n in zip(s["percentile"], s["score"], s["cat_size"])]
    s["base_grade"] = [g for g, _ in graded]
    s["grade"] = s["base_grade"]
    s["signal"] = [sig for _, sig in graded]
    if prev_grades is not None:
        apply_strong_buy(s, prev_grades)
    s["overall_rank"] = s["score"].rank(ascending=False, method="min").astype(int)
    return s.sort_values("score", ascending=False)


GRADE_SIGNAL = {"A+": "GÜÇLÜ AL", "A": "AL", "B": "İZLE", "C": "ZAYIF", "D": "UZAK DUR"}
GRADE_ORDER = ["A+", "A", "B", "C", "D"]


def apply_strong_buy(s: pd.DataFrame, prev_grades: list[pd.Series]) -> None:
    """A+ / GÜÇLÜ AL için ek şartlar; sağlamayan üst fonlar A / AL olur.
    Kurucu riski olan fonların notu en fazla B / İZLE olabilir. (Yerinde değiştirir.)"""
    cfg = config.STRONG_BUY
    s["sb_top"] = s["percentile"] > cfg["top_percentile"]
    s["sb_history"] = s["history_days"] >= cfg["min_history_days"]
    s["sb_investors"] = s["investors"].fillna(0) >= cfg["min_investors"]
    s["sb_aum"] = s["aum"].fillna(0) >= cfg["min_aum"]
    s["sb_anomaly"] = s["p_anomaly"] <= 0
    streak = pd.Series(len(prev_grades) >= cfg["streak_months"], index=s.index)
    for g in prev_grades[-cfg["streak_months"]:]:
        streak &= g.reindex(s.index).isin(["A+", "A"])
    s["sb_streak"] = streak
    s["sb_founder"] = ~s["founder_risk"]
    ok = (s["sb_top"] & s["sb_history"] & s["sb_investors"] & s["sb_aum"]
          & s["sb_anomaly"] & s["sb_streak"] & s["sb_founder"])
    grade = s["base_grade"].where(s["base_grade"] != "A+", "A")
    grade = grade.mask(ok, "A+")
    cap = config.FOUNDER_RISK["max_grade"]
    capped = s["founder_risk"] & grade.map(GRADE_ORDER.index).lt(GRADE_ORDER.index(cap))
    grade = grade.mask(capped, cap)
    s["grade"] = grade
    s["signal"] = grade.map(GRADE_SIGNAL)


def month_ends(index: pd.DatetimeIndex) -> list[int]:
    """Her tamamlanmış ayın son işlem gününün satır numarası (son, süren ay hariç)."""
    pos = pd.Series(range(len(index)), index=index)
    last = pos.groupby(index.to_period("M")).max()
    return [int(i) for i in last.values[:-1]]


def base_grades_at(panel: dict, funds: pd.DataFrame, i: int) -> pd.Series:
    """i. işlem gününde yalnızca o güne kadarki veriyle temel (göreli) notlar."""
    sub = {k: v.iloc[: i + 1] for k, v in panel.items() if isinstance(v, pd.DataFrame)}
    m, _, _ = compute_metrics(sub, funds, light=True)
    return score_funds(m)["base_grade"]


def run(conn: sqlite3.Connection) -> dict:
    panel = load_panel(conn)
    funds = load_funds(conn)
    metrics, excluded, rf = compute_metrics(panel, funds)

    # Süreklilik: önceki tamamlanmış ay sonlarındaki temel notlar (o günün verisiyle;
    # FVT işlem bayrağı geçmişte bilinemeyeceği için kullanılmaz)
    funds_pit = funds.copy()
    funds_pit["trading_active"] = np.nan
    ends = [i for i in month_ends(panel["price"].index) if i >= MIN_HISTORY_FOR_GRADES]
    prev = [base_grades_at(panel, funds_pit, i) for i in ends[-config.STRONG_BUY["streak_months"]:]]

    risky = founder_risk(funds, metrics.index, excluded)
    flag = funds["founder"].reindex(metrics.index).isin(risky)
    scored = score_funds(metrics, founder_flag=flag, prev_grades=prev)
    scored = scored.join(funds[["name", "qualified", "category_src", "founder"]], how="left")

    as_of = panel["price"].index[-1].strftime("%Y-%m-%d")
    conn.executemany(
        "INSERT OR REPLACE INTO scores (date, code, score, signal, category) VALUES (?, ?, ?, ?, ?)",
        [(as_of, c, float(r.score), r.signal, r.category) for c, r in scored.iterrows()],
    )
    conn.commit()
    print(f"[skor] {as_of}: {len(scored)} fon skorlandı, {len(excluded)} dışlandı,"
          f" {metrics.attrs['private_skipped']} özel fon alınmadı, {len(panel['splits'])} pay bölünmesi düzeltildi,"
          f" rf=%{rf*100:.1f}", flush=True)
    return {
        "as_of": as_of,
        "first_date": panel["price"].index[0].strftime("%Y-%m-%d"),
        "scored": scored,
        "excluded": excluded,
        "risk_free": rf,
        "founder_risk": risky,
        "private_skipped": metrics.attrs["private_skipped"],
        "splits": panel["splits"],
        "panel": panel,
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }

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
QUALIFIED_RE = re.compile(r"SERBEST|N[İI]TEL[İI]KL[İI]|G[İI]R[İI][ŞS][İI]M SERMAYES[İI]|GAYR[İI]MENKUL")


# =================================================================== veri

def load_panel(conn: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    df = pd.read_sql("SELECT date, code, price, shares, investors, size FROM prices", conn)
    df["date"] = pd.to_datetime(df["date"])
    panel = {
        col: df.pivot(index="date", columns="code", values=col).sort_index()
        for col in ("price", "shares", "investors", "size")
    }
    return panel


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


def load_funds(conn: sqlite3.Connection) -> pd.DataFrame:
    funds = pd.read_sql(
        "SELECT code, name, category, category_src, fee, stopaj, trading_active, is_serbest FROM funds",
        conn,
    ).set_index("code")
    funds["category"] = funds["category"].fillna(funds["name"].map(categorize))
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


def compute_metrics(panel: dict[str, pd.DataFrame], funds: pd.DataFrame) -> tuple[pd.DataFrame, list, float]:
    price = panel["price"]
    universe_last = price.index[-1]
    last_seen = price.apply(pd.Series.last_valid_index)
    first_seen = price.apply(pd.Series.first_valid_index)
    n_obs = price.notna().sum()

    # ---- dışlananlar
    stale_cutoff = universe_last - pd.Timedelta(days=config.STALE_PRICE_DAYS)
    excluded = []
    keep = []
    for code in price.columns:
        if last_seen[code] < stale_cutoff:
            halted = funds.at[code, "trading_active"] == 0 if code in funds.index else False
            excluded.append({
                "code": code,
                "name": funds.at[code, "name"] if code in funds.index else code,
                "lastDate": last_seen[code].strftime("%Y-%m-%d"),
                "reason": "TEFAS işlemi durdurulmuş" if halted else "Fiyat yayımlanmıyor",
            })
        elif n_obs[code] >= config.MIN_HISTORY_DAYS:
            keep.append(code)

    # Kısa tatilleri doldur (fon bazlı tatil / geç yayın), uzun boşlukları değil
    px = price[keep].ffill(limit=5)
    rets = price[keep].pct_change(fill_method=None).clip(-0.5, 1.0)
    category = funds["category"].reindex(keep).fillna("Diğer")

    m = pd.DataFrame(index=keep)
    m["category"] = category

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
    for cat, codes in category.groupby(category).groups.items():
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
    """Kategori içi yüzdelik (0-100]; eksik değer kategori medyanı sayılır."""
    s = pd.to_numeric(s, errors="coerce")
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


def score_funds(m: pd.DataFrame) -> pd.DataFrame:
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

    s["rank"] = s.groupby("category")["score"].rank(ascending=False, method="min").astype(int)
    s["cat_size"] = s.groupby("category")["score"].transform("count").astype(int)
    s["percentile"] = (s["cat_size"] - s["rank"] + 1) / s["cat_size"] * 100
    graded = [rating(p, sc, n) for p, sc, n in zip(s["percentile"], s["score"], s["cat_size"])]
    s["grade"] = [g for g, _ in graded]
    s["signal"] = [sig for _, sig in graded]
    s["overall_rank"] = s["score"].rank(ascending=False, method="min").astype(int)
    return s.sort_values("score", ascending=False)


def run(conn: sqlite3.Connection) -> dict:
    panel = load_panel(conn)
    funds = load_funds(conn)
    metrics, excluded, rf = compute_metrics(panel, funds)
    scored = score_funds(metrics)
    scored = scored.join(funds[["name", "qualified", "category_src"]], how="left")

    as_of = panel["price"].index[-1].strftime("%Y-%m-%d")
    conn.executemany(
        "INSERT OR REPLACE INTO scores (date, code, score, signal, category) VALUES (?, ?, ?, ?, ?)",
        [(as_of, c, float(r.score), r.signal, r.category) for c, r in scored.iterrows()],
    )
    conn.commit()
    print(f"[skor] {as_of}: {len(scored)} fon skorlandı, {len(excluded)} dışlandı, rf=%{rf*100:.1f}", flush=True)
    return {
        "as_of": as_of,
        "first_date": panel["price"].index[0].strftime("%Y-%m-%d"),
        "scored": scored,
        "excluded": excluded,
        "risk_free": rf,
        "panel": panel,
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }

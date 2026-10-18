import datetime
import hashlib
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import streamlit as st
import sqlite3

from app.services import scoring_engine
from fund_attributes import refresh_fund_attributes

try:
    from config.settings import (
        ANOMALY_MAX_PENALTY,
        ANOMALY_PENALTY_PER_Z,
        ANOMALY_Z_THRESHOLD,
        RATING_MODE,
        STALE_PRICE_DAYS,
    )
except ImportError:
    STALE_PRICE_DAYS = 7
    ANOMALY_Z_THRESHOLD, ANOMALY_PENALTY_PER_Z, ANOMALY_MAX_PENALTY = 3.0, 2.0, 15.0
    RATING_MODE = "relative"

try:
    from tefas import Crawler

    tefas_crawler = Crawler(fund_limit=1000)
    TEFAS_LIB_READY = True
except ImportError:
    TEFAS_LIB_READY = False


def get_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "tefas.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS funds (id INTEGER PRIMARY KEY"
        " AUTOINCREMENT, code TEXT UNIQUE, title TEXT, category TEXT, status TEXT"
        " DEFAULT 'ACTIVE', is_qualified INTEGER DEFAULT 0, history_completed"
        " INTEGER DEFAULT 0)"
    )
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS fund_daily_prices (fund_id INTEGER, date"
        " TEXT, price REAL, PRIMARY KEY (fund_id, date))"
    )
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS fund_scores (fund_id INTEGER, date TEXT,"
        " absolute_score REAL, final_score REAL, confidence_score REAL,"
        " category_rank INTEGER, category_total INTEGER, category_percentile"
        " REAL, signal TEXT, letter_grade TEXT, breakdown_json TEXT, raw_score"
        " REAL, confidence_factor REAL, PRIMARY KEY (fund_id, date))"
    )
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)"
    )
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fund_flow_metrics (
        fund_id INTEGER,
        date TEXT,
        investor_count INTEGER,
        investor_growth_1m REAL,
        fund_size REAL,
        fund_size_growth_1m REAL,
        cash_flow REAL,
        source TEXT,
        PRIMARY KEY (fund_id, date)
    )
    """)

    migrations = [
        ("funds", "is_qualified INTEGER DEFAULT 0"),
        ("funds", "history_completed INTEGER DEFAULT 0"),
        ("fund_scores", "absolute_score REAL"),
        ("fund_scores", "final_score REAL"),
        ("fund_scores", "category_rank INTEGER"),
        ("fund_scores", "category_total INTEGER"),
        ("fund_scores", "category_percentile REAL"),
        ("fund_scores", "letter_grade TEXT"),
        ("fund_scores", "signal TEXT"),
        ("fund_scores", "confidence_score REAL"),
        ("fund_scores", "breakdown_json TEXT"),
        ("fund_scores", "raw_score REAL"),
        ("fund_scores", "confidence_factor REAL"),
    ]
    for table, col_def in migrations:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    return conn


def detect_qualified_fund(title, category):
    text = f"{str(title).upper()} {str(category).upper()}"
    # "ÖZEL SEKTÖR BORÇLANMA ARAÇLARI" fonları herkese açık; "ÖZEL" anahtar
    # kelimesine takılıp nitelikli sayılmasınlar.
    text = text.replace("ÖZEL SEKTÖR", "")
    qualified_keywords = [
        "SERBEST",
        "ÖZEL",
        "GİRİŞİM",
        "GAYRİMENKUL",
        "NİTELİKLİ",
        "HEDGE",
    ]
    for kw in qualified_keywords:
        if kw in text:
            return 1
    return 0


def calculate_portfolio_quality(aum, alpha):
    score = 0

    # AUM büyüklüğü
    if aum >= 1_000_000_000:
        score += 60
    elif aum >= 500_000_000:
        score += 50
    elif aum >= 100_000_000:
        score += 40
    elif aum >= 10_000_000:
        score += 25
    else:
        score += 10

    # Alpha katkısı
    if alpha >= 5:
        score += 40
    elif alpha >= 2:
        score += 30
    elif alpha >= 0:
        score += 20
    else:
        score += 5

    return min(score, 100)


def _present(x):
    return x is not None and not (isinstance(x, float) and np.isnan(x))


def weighted_cash_flow(external, flow):
    """3A %60 / 1A %30 / 1H %10; eksik dönemlerin ağırlığı kalanlara dağıtılır."""
    parts = [
        (external.get("flow_3m"), 0.60),
        (external.get("flow_1m"), 0.30),
        (external.get("flow_1w"), 0.10),
    ]
    parts = [(float(v), w) for v, w in parts if _present(v)]
    if parts:
        total_w = sum(w for _, w in parts)
        return sum(v * w for v, w in parts) / total_w
    value = flow.get("cash_flow")
    return float(value) if _present(value) else 0.0


def calculate_return_anomaly_penalty(df):
    """Kategori içi 1Y getiri robust z-skoru eşiği aşan fonlara ceza puanı."""
    def per_category(group):
        r = group["r_365"].astype(float)
        if len(r) < 5:
            return pd.Series(0.0, index=group.index)
        iqr = r.quantile(0.75) - r.quantile(0.25)
        z = (r - r.median()) / max(iqr, 1e-6)
        penalty = (z - ANOMALY_Z_THRESHOLD).clip(lower=0) * ANOMALY_PENALTY_PER_Z
        return penalty.clip(upper=ANOMALY_MAX_PENALTY)

    return pd.concat(
        [per_category(group) for _, group in df.groupby("category")]
    ).reindex(df.index).fillna(0.0)


def calculate_relative_rating(percentile):
    """Kategori içi dağılım: üst %10 A+, sonraki %22.5 A, %35 B, %22.5 C, alt %10 D."""
    if percentile > 90:
        return "A+", "GÜÇLÜ AL"
    elif percentile > 67.5:
        return "A", "AL"
    elif percentile > 32.5:
        return "B", "İZLE"
    elif percentile > 10:
        return "C", "ZAYIF"
    else:
        return "D", "UZAK DUR"


def run_batch_scoring_engine(conn):
    recategorized, newly_qualified = refresh_fund_attributes(conn)
    print(f"Kategori düzeltilen: {recategorized} | serbest -> nitelikli: {newly_qualified}")

    funds_df = pd.read_sql(
        "SELECT id, code, category FROM funds WHERE status = 'ACTIVE'", con=conn
    )
    if funds_df.empty:
        return
    funds_df["category"] = funds_df["category"].fillna("Diğer")

    # fund_daily_prices'ta (fund_id, date) tekil değil; tekrarlı satırlar ve
    # 0 fiyatlar getiri pencerelerini bozuyordu. Her gün için son kaydı al.
    prices_df = pd.read_sql(
        "SELECT fund_id, date, price FROM fund_daily_prices WHERE id IN"
        " (SELECT MAX(id) FROM fund_daily_prices WHERE price > 0"
        " GROUP BY fund_id, date) ORDER BY fund_id, date ASC",
        con=conn,
    )
    if prices_df.empty:
        return

    metrics_df = pd.read_sql(
        """
    SELECT 
    fund_id,
    sharpe_ratio,
    sortino_ratio,
    volatility,
    max_drawdown,
    alpha,
    information_ratio,
    recovery_time,
    calmar_ratio,
    beta
    FROM fund_metrics
    WHERE date = (SELECT MAX(date) FROM fund_metrics)
    """,
        con=conn,
    )

    metric_map = metrics_df.set_index("fund_id").to_dict("index")

    info_df = pd.read_sql(
        """
    SELECT
        fu.id AS fund_id,
        f.investor_count,
        f.investor_growth_1m,
        f.fund_size,
        f.fund_size_growth_1m,
        f.cash_flow,
        i.management_fee,
        i.withholding_tax,
        e.investor_count AS external_investor_count,
        e.aum AS external_aum,
        e.flow_1w AS external_flow_1w,
        e.flow_1m AS external_flow_1m,
        e.flow_3m AS external_flow_3m,
        e.management_fee AS external_management_fee,
        e.stopaj AS external_stopaj,
        e.trading_active AS external_trading_active
    FROM funds fu
    LEFT JOIN fund_flow_metrics f
    ON f.fund_id = fu.id
    AND f.date = (SELECT MAX(date) FROM fund_flow_metrics)
    LEFT JOIN fund_info_metrics i
    ON fu.id = i.fund_id
    LEFT JOIN fund_external_metrics e
    ON fu.id = e.fund_id
    """,
        con=conn,
    )
    info_map = info_df.set_index("fund_id").to_dict("index")

    flow_df = pd.read_sql(
        """
    SELECT
    fund_id,
    investor_growth_1m,
    fund_size_growth_1m,
    cash_flow,
    source
    FROM fund_flow_metrics
    WHERE date = (
        SELECT MAX(date)
        FROM fund_flow_metrics
    )
    """,
        con=conn,
    )
    flow_map = flow_df.set_index("fund_id").to_dict("index")

    grouped = dict(tuple(prices_df.groupby("fund_id")))
    raw_data = []
    excluded = []

    universe_last_date = pd.to_datetime(prices_df["date"].max())
    stale_cutoff = universe_last_date - datetime.timedelta(days=STALE_PRICE_DAYS)

    # 1. HAM VERİLERİ HAZİRLAMA (FVT Öncelikli Hiyerarşi)
    for _, row in funds_df.iterrows():
        f_id = row["id"]
        category = row["category"]
        if f_id not in grouped:
            continue

        p_history = grouped[f_id]
        valid_history = (
            p_history[p_history["price"] > 0]
            .sort_values("date")
        )
        prices = valid_history["price"].values
        if len(prices) < 30:
            continue

        # Fiyatı güncellenmeyen fonlar skorlanmaz. FVT'nin islem=0 bayrağı tek başına
        # yetmez (TEFAS'ta hiç işlem görmeyen ama fiyatı yayımlanan fonlarda da 0);
        # yalnızca nedeni ayırt etmek için kullanılır.
        if pd.to_datetime(valid_history["date"].iloc[-1]) < stale_cutoff:
            halted = info_map.get(f_id, {}).get("external_trading_active") == 0
            excluded.append((
                row["code"],
                "TEFAS işlemi durdurulmuş, fiyat yayımlanmıyor"
                if halted
                else "fiyat güncel değil",
            ))
            continue

        day_count = len(prices)

        # Fiyat serisi işlem günü bazlı: 1 ay ~ 21, 1 yıl ~ 252 işlem günü.
        # (Eskiden 365/1825 satır geri gidiliyordu; bu ~1.45 / ~7.2 yıl ediyordu.)
        def trailing_return(n_days, fallback):
            if day_count > n_days:
                return (prices[-1] / prices[-1 - n_days] - 1) * 100
            return fallback

        r_30 = trailing_return(21, 0)
        r_60 = trailing_return(42, r_30)
        r_90 = trailing_return(63, r_30)
        r_180 = trailing_return(126, r_90)
        r_270 = trailing_return(189, r_180)
        r_365 = trailing_return(252, r_180)
        r_1095 = trailing_return(756, r_365)
        r_1825 = trailing_return(1260, r_1095)

        daily_returns = pd.Series(prices).pct_change().dropna()
        volatility = (
            float(daily_returns.std() * (252**0.5))
            if len(daily_returns) > 5
            else 0.2
        )
        mean_ret = float(daily_returns.mean()) if len(daily_returns) > 0 else 0

        m = metric_map.get(f_id, {})
        info = info_map.get(f_id, {})
        flow = flow_map.get(f_id, {})

        external = {
            "investor_count": info.get("external_investor_count"),
            "aum": info.get("external_aum"),
            "flow_1w": info.get("external_flow_1w"),
            "flow_1m": info.get("external_flow_1m"),
            "flow_3m": info.get("external_flow_3m"),
            "management_fee": info.get("external_management_fee"),
            "stopaj": info.get("external_stopaj"),
        }

        sharpe = (
            m.get("sharpe_ratio")
            if m.get("sharpe_ratio") is not None
            else ((mean_ret * 255) / (volatility + 1e-9))
        )
        sortino = (
            m.get("sortino_ratio")
            if m.get("sortino_ratio") is not None
            else sharpe
        )
        volatility = (
            m.get("volatility") if m.get("volatility") is not None else volatility
        )
        mdd = m.get("max_drawdown") if m.get("max_drawdown") is not None else 0.0
        alpha = m.get("alpha") if m.get("alpha") is not None else 0.0
        information_ratio = (
            m.get("information_ratio")
            if m.get("information_ratio") is not None
            else 0.0
        )

        if m.get("max_drawdown") is None:
            # fund_metrics ile aynı birim: ondalık (0.15 = %15)
            cum_max = np.maximum.accumulate(prices)
            drawdowns = (prices - cum_max) / cum_max
            mdd = float(abs(drawdowns.min())) if len(drawdowns) > 0 else 0.0

        first_date = valid_history["date"].iloc[0]
        last_date = valid_history["date"].iloc[-1]

        conf = scoring_engine.calculate_confidence(prices, first_date, last_date)

        raw_data.append({
            "fund_id": f_id,
            "category": category,
            "sharpe": sharpe,
            "sortino": sortino,
            "volatility": volatility,
            "mdd": mdd,
            "alpha": alpha,
            "beta": m.get("beta", 1),
            "information_ratio": information_ratio,
            "r_30": r_30,
            "r_60": r_60,
            "r_90": r_90,
            "r_180": r_180,
            "r_270": r_270,
            "r_365": r_365,
            "r_1095": r_1095,
            "r_1825": r_1825,
            "real_return_1y": r_365,
            "calmar": m.get("calmar_ratio", 0),
            "portfolio_quality": calculate_portfolio_quality(
                external.get("aum")
                or info.get("aum")
                or flow.get("fund_size")
                or 0,
                alpha,
            ),
            "investor_count": (
                external.get("investor_count")
                or info.get("investor_count")
                or flow.get("investor_count")
                or 0
            ),
            "investor_growth_1m": (
                flow.get("investor_growth_1m", 0)
                if flow.get("source") != "PRICE_PROXY"
                else 0
            ),
            "fund_size_growth_1m": (
                flow.get("fund_size_growth_1m", 0)
                if flow.get("source") != "PRICE_PROXY"
                else 0
            ),
            "cash_flow": weighted_cash_flow(external, flow),
            "aum": (
                external.get("aum")
                or info.get("aum")
                or flow.get("fund_size")
                or 0
            ),
            "management_fee": (
                external.get("management_fee")
                or info.get("management_fee")
                or 0
            ),
            "stopaj": external.get("stopaj") or info.get("withholding_tax") or 0,
            "confidence": conf,
            "age_years": day_count / 365.0,
            "depth_score": min(100, day_count / 3.65),
        })

    if not raw_data:
        return
    df = pd.DataFrame(raw_data)

    # 2. VEKTÖREL HESAPLAMALAR (Kategori bazlı)
    composite_dfs = []
    for cat, group in df.groupby("category"):
        group["perf_percentile"] = scoring_engine.calculate_performance_composite(
            group
        )
        group["risk_percentile"] = scoring_engine.calculate_risk_composite(group)
        group["qual_percentile"] = scoring_engine.calculate_quality_composite(group)
        group["cash_percentile"] = scoring_engine.calculate_cashflow_composite(
            group
        )
        group["cost_percentile"] = scoring_engine.calculate_cost_composite(group)
        composite_dfs.append(group)

    df_scored = pd.concat(composite_dfs)
    df_scored["anomaly_penalty"] = calculate_return_anomaly_penalty(df_scored)

    df_scored["absolute_score"] = scoring_engine.calculate_absolute_score(
        df_scored["perf_percentile"],
        df_scored["risk_percentile"],
        df_scored["cash_percentile"],
        df_scored["qual_percentile"],
        df_scored["cost_percentile"],
    )

    final_scores = []
    for _, row in df_scored.iterrows():
        tot_pen = 0
        mdd_pen = 0
        vol_pen = 0

        investor_penalty = scoring_engine.calculate_investor_penalty(
            row["investor_count"]
        )
        tot_pen += investor_penalty

        final_sc, raw_score, conf_factor = scoring_engine.calculate_final_score(
            row["absolute_score"], tot_pen, row["confidence"]
        )

        investor_adjustment = (
            scoring_engine.calculate_investor_stability_adjustment(
                row["investor_count"]
            )
        )

        # Büyük nakit çıkışı ek cezası
        cash_flow_penalty = 0
        cash_ratio = 0
        try:
            aum = float(row["aum"])
            cash_flow = float(row["cash_flow"])

            if aum > 0:
                cash_ratio = (cash_flow / aum) * 100

                # Aşırı uç değerleri sınırla
                cash_ratio = max(-100, min(100, cash_ratio))

                if cash_ratio < -30:
                    cash_flow_penalty = 8
                elif cash_ratio < -20:
                    cash_flow_penalty = 5
                elif cash_ratio < -10:
                    cash_flow_penalty = 3
                elif cash_ratio < -5:
                    cash_flow_penalty = 1
                else:
                    cash_flow_penalty = 0
        except:
            pass

        anomaly_penalty = float(row["anomaly_penalty"])
        raw_score = raw_score - (cash_flow_penalty * 0.50) - anomaly_penalty
        final_sc = raw_score + ((conf_factor - 0.5) * 10)
        final_sc = final_sc + investor_adjustment
        final_sc = max(0, min(100, final_sc))

        row["investor_penalty"] = investor_penalty
        row["investor_adjustment"] = investor_adjustment
        row["cash_flow_penalty"] = cash_flow_penalty

        breakdown_json = scoring_engine.explain_score(
            row["perf_percentile"],
            row["risk_percentile"],
            row["cash_percentile"],
            row["qual_percentile"],
            row["cost_percentile"],
            row["absolute_score"],
            mdd_pen,
            vol_pen,
            raw_score,
            row["confidence"],
            conf_factor,
            final_sc,
        )
        breakdown = json.loads(breakdown_json)
        breakdown["penalties"]["cash_flow"] = cash_flow_penalty
        breakdown["penalties"]["return_anomaly"] = round(anomaly_penalty, 2)
        breakdown["cash_flow_ratio"] = round(cash_ratio, 2)
        breakdown_json = json.dumps(
            breakdown,
            ensure_ascii=False
        )

        final_scores.append({
            "fund_id": row["fund_id"],
            "final_score": final_sc,
            "raw_score": raw_score,
            "confidence_factor": conf_factor,
            "breakdown_json": breakdown_json,
        })

    df_final = pd.DataFrame(final_scores)
    df_scored = pd.merge(df_scored, df_final, on="fund_id")

    # 3. KATEGORİ İÇİ PERCENTILE
    df_scored["final_percentile"] = scoring_engine.calculate_category_percentile(
        df_scored
    )

    df_scored["category_rank"] = (
        df_scored.groupby("category")["final_score"]
        .rank(ascending=False, method="min")
    )

    df_scored["category_total"] = (
        df_scored.groupby("category")["final_score"].transform("count")
    )

    df_scored["category_percentile"] = (
        (df_scored["category_total"] - df_scored["category_rank"] + 1)
        / df_scored["category_total"]
    ) * 100

    # 4. VERİTABANI KAYITLARI
    # Skor, hesaplamada kullanılan son fiyat gününe aittir. Tarihi geriye kaydırmak
    # (eskiden -1260 gün) backtest'e geleceği bilen skorlar sokuyordu (look-ahead).
    today_str = str(prices_df["date"].max())[:10]
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES ('excluded_funds', ?)",
        (json.dumps(excluded, ensure_ascii=False),),
    )
    cursor.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_sync', ?)",
        (datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"),),
    )
    print(f"Skorlanan: {len(df_scored)} | Dışlanan: {len(excluded)} -> {excluded[:20]}")
    db_records = []

    for _, row in df_scored.iterrows():
        if RATING_MODE == "relative" and row["category_total"] >= 5:
            grade, signal = calculate_relative_rating(row["category_percentile"])
        else:
            grade, signal = scoring_engine.calculate_rating(
                row["final_score"], row["confidence"]
            )

        db_records.append((
            int(row["fund_id"]),
            today_str,
            float(row["absolute_score"]),
            float(row["final_score"]),
            float(row["confidence"]),
            int(row["category_rank"]),
            int(row["category_total"]),
            float(row["category_percentile"]),
            signal,
            grade,
            row["breakdown_json"],
            float(row["raw_score"]),
            float(row["confidence_factor"]),
        ))

    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT OR REPLACE INTO fund_scores 
        (fund_id, date, absolute_score, final_score, confidence_score, category_rank, category_total, category_percentile, signal, letter_grade, breakdown_json, raw_score, confidence_factor) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        db_records,
    )
    conn.commit()


# TEFAS API Crawler Fonksiyonları
def safe_fetch(start_date, end_date, max_retries=3):
    for attempt in range(max_retries):
        try:
            return tefas_crawler.fetch(start=start_date, end=end_date)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(random.uniform(2.0, 5.0) * (attempt + 1))
            else:
                raise e
    return None


def fetch_chunk_worker(args):
    s_str, e_str, codes_subset = args
    try:
        time.sleep(random.uniform(0.3, 1.5))
        df = safe_fetch(start_date=s_str, end_date=e_str)
        if df is not None and not df.empty:
            return df[df["code"].isin(codes_subset)]
    except Exception:
        pass
    return None


def run_tefas_sync_and_scoring(full_sync=False, *args, **kwargs):
    if not TEFAS_LIB_READY:
        return False, "TEFAS kütüphanesi yüklü değil!"

    conn = get_db_connection()
    try:
        run_batch_scoring_engine(conn)
        return (
            True,
            "Başarılı! Kurumsal Standartlarda V3.1 Kantitatif Motoru çalıştırıldı.",
        )
    except Exception as e:
        return False, f"Hata: {str(e)}"
    finally:
        conn.close()


if __name__ == "__main__":
    conn = get_db_connection()
    try:
        run_batch_scoring_engine(conn)
        print("SCORING TAMAMLANDI")
    except Exception as e:
        print(f"HATA: {e}")
    finally:
        conn.close()
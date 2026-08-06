import pandas as pd
import numpy as np
import sqlite3
import datetime
import os
import time
import random
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.services import scoring_engine 

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
    cursor.execute("CREATE TABLE IF NOT EXISTS funds (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, title TEXT, category TEXT, status TEXT DEFAULT 'ACTIVE', is_qualified INTEGER DEFAULT 0, history_completed INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS fund_daily_prices (fund_id INTEGER, date TEXT, price REAL, PRIMARY KEY (fund_id, date))")
    cursor.execute("CREATE TABLE IF NOT EXISTS fund_scores (fund_id INTEGER, date TEXT, absolute_score REAL, final_score REAL, confidence_score REAL, category_rank INTEGER, category_total INTEGER, category_percentile REAL, signal TEXT, letter_grade TEXT, breakdown_json TEXT, raw_score REAL, confidence_factor REAL, PRIMARY KEY (fund_id, date))")
    cursor.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
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
        ("fund_scores", "confidence_factor REAL")
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
    qualified_keywords = ["SERBEST", "ÖZEL", "GİRİŞİM", "GAYRİMENKUL", "NİTELİKLİ", "HEDGE"]
    for kw in qualified_keywords:
        if kw in text: return 1
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

def run_batch_scoring_engine(conn):
    funds_df = pd.read_sql("SELECT id, code, category FROM funds WHERE status = 'ACTIVE'", con=conn)
    if funds_df.empty: return
    
    prices_df = pd.read_sql("SELECT fund_id, date, price FROM fund_daily_prices ORDER BY fund_id, date ASC", con=conn)
    if prices_df.empty: return

    metrics_df = pd.read_sql("""
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
    """, con=conn)

    metric_map = metrics_df.set_index("fund_id").to_dict("index")

    info_df = pd.read_sql("""
    SELECT
        f.fund_id,
        f.investor_count,
        f.investor_growth_1m,
        f.fund_size,
        f.fund_size_growth_1m,
        f.cash_flow,
        i.management_fee,
        i.withholding_tax,
        e.investor_count AS external_investor_count,
        e.aum AS external_aum,
        e.management_fee AS external_management_fee,
        e.stopaj AS external_stopaj
    FROM fund_flow_metrics f
    LEFT JOIN fund_info_metrics i
    ON f.fund_id = i.fund_id
    LEFT JOIN fund_external_metrics e
    ON f.fund_id = e.fund_id
    WHERE f.date = (
        SELECT MAX(date)
        FROM fund_flow_metrics
    )
    """, con=conn)
    info_map = info_df.set_index("fund_id").to_dict("index")

    flow_df = pd.read_sql("""
    SELECT
    fund_id,
    investor_growth_1m,
    fund_size_growth_1m,
    cash_flow
    FROM fund_flow_metrics
    WHERE date = (
        SELECT MAX(date)
        FROM fund_flow_metrics
    )
    """, con=conn)
    flow_map = flow_df.set_index("fund_id").to_dict("index")

    grouped = dict(tuple(prices_df.groupby('fund_id')))
    raw_data = []

    # 1. HAM VERİLERİ HAZİRLAMA (FVT Öncelikli Hiyerarşi)
    for _, row in funds_df.iterrows():
        f_id = row['id']
        category = row['category']
        if f_id not in grouped: continue
        
        p_history = grouped[f_id]
        prices = p_history['price'].values
        prices = prices[prices > 0]
        if len(prices) < 30: continue
        
        day_count = len(prices)
        r_30 = (prices[-1] / prices[-30] - 1) * 100 if day_count >= 30 else 0
        r_90 = (prices[-1] / prices[-90] - 1) * 100 if day_count >= 90 else r_30
        r_180 = (prices[-1] / prices[-180] - 1) * 100 if day_count >= 180 else r_90
        r_365 = (prices[-1] / prices[-365] - 1) * 100 if day_count >= 365 else r_180

        daily_returns = pd.Series(prices).pct_change().dropna()
        volatility = float(daily_returns.std() * (255 ** 0.5)) if len(daily_returns) > 5 else 0.2
        mean_ret = float(daily_returns.mean()) if len(daily_returns) > 0 else 0
        
        m = metric_map.get(f_id, {})
        info = info_map.get(f_id, {})
        flow = flow_map.get(f_id, {})
        
        external = {
            'investor_count': info.get('external_investor_count'),
            'aum': info.get('external_aum'),
            'management_fee': info.get('external_management_fee'),
            'stopaj': info.get('external_stopaj')
        }
        
        sharpe = m.get('sharpe_ratio') if m.get('sharpe_ratio') is not None else ((mean_ret * 255) / (volatility + 1e-9))
        sortino = m.get('sortino_ratio') if m.get('sortino_ratio') is not None else sharpe
        volatility = m.get('volatility') if m.get('volatility') is not None else volatility
        mdd = m.get('max_drawdown') if m.get('max_drawdown') is not None else 0.0
        alpha = m.get('alpha') if m.get('alpha') is not None else 0.0
        information_ratio = m.get('information_ratio') if m.get('information_ratio') is not None else 0.0

        if m.get('max_drawdown') is None:
            cum_max = np.maximum.accumulate(prices)
            drawdowns = (prices - cum_max) / cum_max
            mdd = float(abs(drawdowns.min()) * 100) if len(drawdowns) > 0 else 0.0

        first_date = p_history['date'].iloc[0]
        last_date = p_history['date'].iloc[-1]
        
        conf = scoring_engine.calculate_confidence(prices, first_date, last_date)

        raw_data.append({
            'fund_id': f_id, 
            'category': category,
            'sharpe': sharpe,
            'sortino': sortino,
            'volatility': volatility,
            'mdd': mdd,
            'alpha': alpha,
            'beta': m.get('beta', 1),
            'information_ratio': information_ratio,
            'r_30': r_30,
            'r_90': r_90,
            'r_180': r_180,
            'r_365': r_365,
            'real_return_1y': r_365,
            'calmar': m.get('calmar_ratio', 0),
            'portfolio_quality': calculate_portfolio_quality(
                (
                    external.get('aum')
                    or info.get('aum')
                    or flow.get('fund_size')
                    or 0
                ),
                alpha
            ),
            'investor_count': (
                external.get('investor_count')
                or info.get('investor_count')
                or flow.get('investor_count')
                or 0
            ),
            'investor_growth_1m': flow.get('investor_growth_1m', 0),
            'fund_size_growth_1m': info.get('fund_size_growth_1m', flow.get('fund_size_growth_1m', 0)),
            'cash_flow': flow.get('cash_flow', 0),
            'aum': (
                external.get('aum')
                or info.get('aum')
                or flow.get('fund_size')
                or 0
            ),
            'management_fee': (
                external.get('management_fee')
                or info.get('management_fee')
                or 0
            ),
            'stopaj': (
                external.get('stopaj')
                or info.get('withholding_tax')
                or 0
            ),
            'confidence': conf,
            'age_years': day_count / 365.0,
            'depth_score': min(100, day_count / 3.65)
        })

    if not raw_data: return
    df = pd.DataFrame(raw_data)

    # 2. VEKTÖREL HESAPLAMALAR (Kategori bazlı)
    composite_dfs = []
    for cat, group in df.groupby('category'):
        group['perf_percentile'] = scoring_engine.calculate_performance_composite(group)
        group['risk_percentile'] = scoring_engine.calculate_risk_composite(group)
        group['qual_percentile'] = scoring_engine.calculate_quality_composite(group)
        group['cash_percentile'] = scoring_engine.calculate_cashflow_composite(group)
        group['cost_percentile'] = scoring_engine.calculate_cost_composite(group)
        composite_dfs.append(group)

    df_scored = pd.concat(composite_dfs)
    
    df_scored['absolute_score'] = scoring_engine.calculate_absolute_score(
        df_scored['perf_percentile'],
        df_scored['risk_percentile'],
        df_scored['cash_percentile'],
        df_scored['qual_percentile'],
        df_scored['cost_percentile']
    )

    final_scores = []
    for _, row in df_scored.iterrows():
        tot_pen = 0
        mdd_pen = 0
        vol_pen = 0
        
        investor_penalty = 0
        tot_pen += investor_penalty
        
        final_sc, raw_score, conf_factor = scoring_engine.calculate_final_score(
            row['absolute_score'], tot_pen, row['confidence']
        )
        
        investor_adjustment = scoring_engine.calculate_investor_stability_adjustment(
            row['investor_count']
        )
        final_sc = final_sc + investor_adjustment
        final_sc = max(0, min(100, final_sc))
        
        row['investor_penalty'] = investor_penalty
        row['investor_adjustment'] = investor_adjustment
        
        breakdown_json = scoring_engine.explain_score(
            row['perf_percentile'] * 0.35,
            row['risk_percentile'] * 0.25,
            row['cash_percentile'] * 0.20,
            row['qual_percentile'] * 0.10,
            row['cost_percentile'] * 0.10,
            row['absolute_score'],
            mdd_pen,
            vol_pen,
            raw_score,
            row['confidence'],
            conf_factor,
            final_sc
        )
        
        final_scores.append({
            'fund_id': row['fund_id'],
            'final_score': final_sc,
            'raw_score': raw_score,
            'confidence_factor': conf_factor,
            'breakdown_json': breakdown_json
        })

    df_final = pd.DataFrame(final_scores)
    df_scored = pd.merge(df_scored, df_final, on='fund_id')

    # 3. KATEGORİ İÇİ PERCENTILE
    df_scored['final_percentile'] = scoring_engine.calculate_category_percentile(df_scored)

    df_scored['category_rank'] = (
        df_scored.groupby('category')['final_score']
        .rank(ascending=False, method='min')
    )

    df_scored['category_total'] = (
        df_scored.groupby('category')['final_score']
        .transform('count')
    )

    df_scored['category_percentile'] = (
        (df_scored['category_total'] - df_scored['category_rank'] + 1)
        / df_scored['category_total']
    ) * 100

    # 4. VERİTABANI KAYITLARI
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    db_records = []

    for _, row in df_scored.iterrows():
        grade, signal = scoring_engine.calculate_rating(
            row['final_score'],
            row['confidence']
        )
        
        db_records.append((
            int(row['fund_id']),
            today_str,
            float(row['absolute_score']),
            float(row['final_score']),
            float(row['confidence']),
            int(row['category_rank']),
            int(row['category_total']),
            float(row['category_percentile']),
            signal,
            grade,
            row['breakdown_json'],
            float(row['raw_score']),
            float(row['confidence_factor'])
        ))

    cursor = conn.cursor()
    cursor.executemany("""
        INSERT OR REPLACE INTO fund_scores 
        (fund_id, date, absolute_score, final_score, confidence_score, category_rank, category_total, category_percentile, signal, letter_grade, breakdown_json, raw_score, confidence_factor) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, db_records)
    conn.commit()


# TEFAS API Crawler Fonksiyonları
def safe_fetch(start_date, end_date, max_retries=3):
    for attempt in range(max_retries):
        try:
            return tefas_crawler.fetch(start=start_date, end=end_date)
        except Exception as e:
            if attempt < max_retries - 1: time.sleep(random.uniform(2.0, 5.0) * (attempt + 1))
            else: raise e
    return None

def fetch_chunk_worker(args):
    s_str, e_str, codes_subset = args
    try:
        time.sleep(random.uniform(0.3, 1.5))
        df = safe_fetch(start_date=s_str, end_date=e_str)
        if df is not None and not df.empty: return df[df['code'].isin(codes_subset)]
    except Exception: pass
    return None

def run_tefas_sync_and_scoring(full_sync=False, *args, **kwargs):
    if not TEFAS_LIB_READY: return False, "TEFAS kütüphanesi yüklü değil!"
    
    conn = get_db_connection()
    try:
        run_batch_scoring_engine(conn)
        return True, "Başarılı! Kurumsal Standartlarda V3.1 Kantitatif Motoru çalıştırıldı."
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
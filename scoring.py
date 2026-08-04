import pandas as pd
import numpy as np
import sqlite3
import datetime
import os
import time
import random
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.services.scoring_engine import QuantitativeFundScorer
from app.services.ranking import calculate_category_percentiles 

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
    cursor.execute("CREATE TABLE IF NOT EXISTS fund_scores (fund_id INTEGER, date TEXT, absolute_score REAL, final_score REAL, confidence_score REAL, category_percentile REAL, signal TEXT, letter_grade TEXT, breakdown_json TEXT, raw_score REAL, confidence_factor REAL, PRIMARY KEY (fund_id, date))")
    cursor.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
    
    migrations = [
        ("funds", "is_qualified INTEGER DEFAULT 0"), 
        ("funds", "history_completed INTEGER DEFAULT 0"), 
        ("fund_scores", "absolute_score REAL"), 
        ("fund_scores", "final_score REAL"), 
        ("fund_scores", "category_percentile REAL"), 
        ("fund_scores", "letter_grade TEXT"), 
        ("fund_scores", "signal TEXT"), 
        ("fund_scores", "confidence_score REAL"), 
        ("fund_scores", "breakdown_json TEXT"),
        ("fund_scores", "raw_score REAL"),
        ("fund_scores", "confidence_factor REAL")
    ]
    for table, col_def in migrations:
        try: cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except sqlite3.OperationalError: pass
        
    conn.commit()
    return conn

def detect_qualified_fund(title, category):
    text = f"{str(title).upper()} {str(category).upper()}"
    qualified_keywords = ["SERBEST", "ÖZEL", "GİRİŞİM", "GAYRİMENKUL", "NİTELİKLİ", "HEDGE"]
    for kw in qualified_keywords:
        if kw in text: return 1
    return 0

def run_batch_scoring_engine(conn):
    funds_df = pd.read_sql("SELECT id, code, category FROM funds WHERE status = 'ACTIVE'", con=conn)
    if funds_df.empty: return
    
    prices_df = pd.read_sql("SELECT fund_id, date, price FROM fund_daily_prices ORDER BY fund_id, date ASC", con=conn)
    if prices_df.empty: return

    grouped = dict(tuple(prices_df.groupby('fund_id')))
    raw_data = []

    # 1. HAM VERİLERİ HAZIRLAMA
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
        sharpe = (mean_ret * 255) / (volatility + 1e-9)
        
        neg_ret = daily_returns[daily_returns < 0]
        downside_vol = float(neg_ret.std() * (255 ** 0.5)) if len(neg_ret) > 3 else volatility
        sortino = (mean_ret * 255) / (downside_vol + 1e-9)

        cum_max = np.maximum.accumulate(prices)
        drawdowns = (prices - cum_max) / cum_max
        mdd = float(abs(drawdowns.min()) * 100) if len(drawdowns) > 0 else 0.0

        first_date = p_history['date'].iloc[0]
        last_date = p_history['date'].iloc[-1]
        
        conf = scoring.calculate_confidence(prices, first_date, last_date)

        raw_data.append({
            'fund_id': f_id, 'category': category,
            'r_30': r_30, 'r_90': r_90, 'r_180': r_180, 'r_365': r_365,
            'sharpe': sharpe, 'sortino': sortino, 'volatility': volatility, 'mdd': mdd,
            'confidence': conf, 'age_years': day_count / 365.0, 'depth_score': min(100, day_count / 3.65)
        })

    if not raw_data: return
    df = pd.DataFrame(raw_data)

    # 2. VEKTÖREL HESAPLAMALAR (Kategori bazlı)
    composite_dfs = []
    for cat, group in df.groupby('category'):
        group['perf_percentile'] = scoring.calculate_performance_composite(group)
        group['risk_percentile'] = scoring.calculate_risk_composite(group)
        group['qual_percentile'] = scoring.calculate_quality_composite(group)
        group['cash_percentile'] = scoring.calculate_cashflow_composite(group)
        group['cost_percentile'] = scoring.calculate_cost_composite(group)
        composite_dfs.append(group)

    df_scored = pd.concat(composite_dfs)
    
    df_scored['absolute_score'] = scoring.calculate_absolute_score(
        df_scored['perf_percentile'], df_scored['risk_percentile'],
        df_scored['qual_percentile'], df_scored['cash_percentile'], df_scored['cost_percentile']
    )

    final_scores = []
    for _, row in df_scored.iterrows():
        tot_pen, mdd_pen, vol_pen = scoring.calculate_continuous_penalty(
            row['mdd'], row['volatility']
        )
        
        final_sc, raw_score, conf_factor = scoring.calculate_final_score(
            row['absolute_score'], tot_pen, row['confidence']
        )
        
        breakdown_json = scoring.explain_score(
            row['perf_percentile']*0.40, row['risk_percentile']*0.30, row['qual_percentile']*0.15, 
            row['cash_percentile']*0.05, row['cost_percentile']*0.10, row['absolute_score'], 
            mdd_pen, vol_pen, raw_score, row['confidence'], conf_factor, final_sc
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
    df_scored['final_percentile'] = scoring.calculate_category_percentile(df_scored)

    # 4. VERİTABANI KAYITLARI
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    db_records = []

    for _, row in df_scored.iterrows():
        # V3.1 Çok Kriterli Rating Mekanizması
        grade, signal = scoring.calculate_rating(
            row['final_score'],
            row['final_percentile'],
            row['confidence']
        )
        
        db_records.append((
            int(row['fund_id']), today_str, float(row['absolute_score']), float(row['final_score']),
            float(row['confidence']), float(row['final_percentile']), signal, grade, row['breakdown_json'],
            float(row['raw_score']), float(row['confidence_factor'])
        ))

    cursor = conn.cursor()
    cursor.executemany("""
        INSERT OR REPLACE INTO fund_scores 
        (fund_id, date, absolute_score, final_score, confidence_score, category_percentile, signal, letter_grade, breakdown_json, raw_score, confidence_factor) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
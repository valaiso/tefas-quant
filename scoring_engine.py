import pandas as pd
import numpy as np
import sqlite3
import datetime
import os
import time
import random
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS funds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            title TEXT,
            category TEXT,
            status TEXT DEFAULT 'ACTIVE',
            is_qualified INTEGER DEFAULT 0,
            history_completed INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fund_daily_prices (
            fund_id INTEGER,
            date TEXT,
            price REAL,
            PRIMARY KEY (fund_id, date)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fund_scores (
            fund_id INTEGER,
            date TEXT,
            absolute_score REAL,
            final_score REAL,
            confidence_score REAL,
            category_percentile REAL,
            signal TEXT,
            letter_grade TEXT,
            breakdown_json TEXT,
            PRIMARY KEY (fund_id, date)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    migrations = [
        ("funds", "is_qualified INTEGER DEFAULT 0"),
        ("funds", "history_completed INTEGER DEFAULT 0"),
        ("fund_scores", "absolute_score REAL"),
        ("fund_scores", "final_score REAL"),
        ("fund_scores", "category_percentile REAL"),
        ("fund_scores", "letter_grade TEXT"),
        ("fund_scores", "signal TEXT"),
        ("fund_scores", "confidence_score REAL"),
        ("fund_scores", "breakdown_json TEXT")
    ]
    for table, col_def in migrations:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    conn.commit()
    return conn

def detect_qualified_fund(title, category):
    text = f"{str(title).upper()} {str(category).upper()}"
    qualified_keywords = ["SERBEST", "ÖZEL", "GİRİŞİM", "GAYRİMENKUL", "NİTELİKLİ", "HEDGE"]
    for kw in qualified_keywords:
        if kw in text:
            return 1
    return 0

# --- 4. CONTINUOUS PENALTY ENGINE (Sürekli Ceza Fonksiyonları) ---
def calculate_continuous_penalties(mdd, volatility, confidence):
    # MDD Cezası (Continuous Piecewise)
    mdd_penalty = 0.0
    if mdd > 60.0:
        mdd_penalty = 5.0 + (mdd - 60.0) * 0.2
    elif mdd > 50.0:
        mdd_penalty = 4.0 + (mdd - 50.0) * 0.1
    elif mdd > 45.0:
        mdd_penalty = 3.0 + (mdd - 45.0) * 0.2
    elif mdd > 40.0:
        mdd_penalty = 2.0 + (mdd - 40.0) * 0.2
    elif mdd > 35.0:
        mdd_penalty = 1.0 + (mdd - 35.0) * 0.2
    
    # Volatilite Cezası
    vol_penalty = 0.0
    if volatility > 0.45:
        vol_penalty = (volatilite - 0.45) * 10.0
    
    # Güven Cezası (Düşük güven oranlarına göre kademeli kesinti)
    conf_penalty = max(0.0, (70.0 - confidence) * 0.08) if confidence < 70 else 0.0

    total_penalty = min(15.0, mdd_penalty + vol_penalty + conf_penalty)
    return total_penalty, {"mdd_penalty": round(mdd_penalty, 2), "vol_penalty": round(vol_penalty, 2), "conf_penalty": round(conf_penalty, 2)}

# --- 7. RATING GATE (Hibrit Harf Notu ve Sinyal) ---
def evaluate_rating_gate(final_score, percentile, confidence):
    if percentile >= 99.0 and final_score >= 80.0 and confidence >= 70.0:
        return 'A+', 'Güçlü AL'
    elif percentile >= 95.0 and final_score >= 75.0 and confidence >= 60.0:
        return 'A', 'AL / İzle'
    elif percentile >= 85.0 and final_score >= 70.0:
        return 'B+', 'Bekle'
    elif percentile >= 70.0:
        return 'B', 'Bekle'
    elif percentile >= 50.0:
        return 'C', 'Zayıf'
    else:
        return 'D', 'Uzak Dur'

# --- 8. CONFIDENCE MATRIX ---
def calculate_confidence(p_history):
    day_count = len(p_history)
    if day_count == 0:
        return 10.0
    
    prices = p_history['price'].values
    prices = prices[prices > 0]
    day_count = len(prices)
    if day_count < 2:
        return 10.0

    age_score = min(100.0, (day_count / 365.0) * 100.0)
    expected_days = (pd.to_datetime(p_history['date'].iloc[-1]) - pd.to_datetime(p_history['date'].iloc[0])).days + 1
    density_score = min(100.0, (day_count / max(1, expected_days)) * 100.0) if expected_days > 0 else 100.0
    integrity_score = 100.0 if day_count > 30 else (day_count / 30.0) * 100.0
    
    last_date = pd.to_datetime(p_history['date'].iloc[-1])
    days_diff = (datetime.date.today() - last_date.date()).days
    recency_score = max(0.0, 100.0 - (days_diff * 5.0))
    
    daily_returns = pd.Series(prices).pct_change().dropna()
    volatility = daily_returns.std() * (255 ** 0.5) if len(daily_returns) > 5 else 0.2
    stability_score = max(0.0, min(100.0, 100.0 - (volatility * 100.0)))

    confidence = (age_score * 0.35) + (density_score * 0.25) + (integrity_score * 0.20) + (recency_score * 0.10) + (stability_score * 0.10)
    return float(min(100.0, max(10.0, confidence)))

# --- 1, 2, 3, 5, 6, 9. PIPELINE & COMPOSITE FACTOR ENGINE ---
def run_batch_scoring_engine(conn):
    funds_df = pd.read_sql("SELECT id, code, category FROM funds WHERE status = 'ACTIVE'", con=conn)
    if funds_df.empty:
        return
    
    fund_ids_str = ",".join(map(str, funds_df['id'].tolist()))
    prices_df = pd.read_sql(f"""
        SELECT fund_id, date, price 
        FROM fund_daily_prices 
        WHERE fund_id IN ({fund_ids_str}) 
        ORDER BY fund_id, date ASC
    """, con=conn)
    
    if prices_df.empty:
        return

    grouped = dict(tuple(prices_df.groupby('fund_id')))
    raw_metrics_list = []

    for _, row in funds_df.iterrows():
        f_id = row['id']
        category = row['category']
        if f_id not in grouped:
            continue
        p_history = grouped[f_id]
        prices = p_history['price'].values
        prices = prices[prices > 0]
        if len(prices) < 15:
            continue
        
        day_count = len(prices)
        r_30 = (prices[-1] / prices[-30] - 1) * 100 if day_count >= 30 else (prices[-1] / prices[0] - 1) * 100
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
        max_drawdown = float(abs(drawdowns.min()) * 100) if len(drawdowns) > 0 else 0.0

        confidence = calculate_confidence(p_history)

        raw_metrics_list.append({
            'fund_id': f_id,
            'category': category,
            'r_30': r_30, 'r_90': r_90, 'r_180': r_180, 'r_365': r_365,
            'sharpe': sharpe, 'sortino': sortino, 'volatility': volatility, 'mdd': max_drawdown,
            'confidence': confidence,
            'fund_age_score': min(100.0, (day_count / 365.0) * 100.0)
        })

    if not raw_metrics_list:
        return

    metrics_df = pd.DataFrame(raw_metrics_list)

    # 2. Composite Factor Engine (Z-Score Normalization per Category)
    def compute_z_score_composite(group_df, cols):
        composite = pd.Series(0.0, index=group_df.index)
        for col in cols:
            s = group_df[col]
            std_val = s.std()
            if std_val == 0 or pd.isna(std_val):
                z = pd.Series(0.0, index=s.index)
            else:
                z = (s - s.mean()) / std_val
            composite += z
        # Min-Max scale to 0-100 within category group
        c_min, c_max = composite.min(), composite.max()
        if c_max == c_min:
            return pd.Series(50.0, index=group_df.index)
        return ((composite - c_min) / (c_max - c_min)) * 100.0

    perf_composites, risk_composites, quality_composites = [], [], []

    for cat, group in metrics_df.groupby('category'):
        g_perf = compute_z_score_composite(group, ['r_30', 'r_90', 'r_180', 'r_365'])
        g_risk = compute_z_score_composite(group, ['sharpe', 'sortino']) - compute_z_score_composite(group, ['volatility', 'mdd'])
        g_risk = ((g_risk - g_risk.min()) / (g_risk.max() - g_risk.min() + 1e-9)) * 100.0
        g_qual = compute_z_score_composite(group, ['confidence', 'fund_age_score'])

        group['perf_comp'] = g_perf
        group['risk_comp'] = g_risk
        group['quality_comp'] = g_qual
        
        # Sabit/Simüle Edilen Komponentler (Para Akışı ve Maliyet)
        group['cashflow_comp'] = 70.0
        group['cost_comp'] = 75.0

        perf_composites.append(group)

    final_metrics_df = pd.concat(perf_composites)

    # 3. Absolute Quant Score (Ağırlıklar: Performans 40, Risk 30, Para Akışı 10, Kalite 10, Maliyet 10)
    final_metrics_df['absolute_score'] = (
        (final_metrics_df['perf_comp'] * 0.40) +
        (final_metrics_df['risk_comp'] * 0.30) +
        (final_metrics_df['cashflow_comp'] * 0.10) +
        (final_metrics_df['quality_comp'] * 0.10) +
        (final_metrics_df['cost_comp'] * 0.10)
    ).clip(0, 100)

    # 4 & 5. Continuous Penalty Engine & Final Score
    final_scores, absolute_scores, confidences, percentiles, grades, signals, breakdowns = [], [], [], [], [], [], []
    today_str = datetime.date.today().strftime('%Y-%m-%d')

    # Ön Hesaplama için kategori içi Final Score bazlı Percentile hazırlığı
    # Önce geçici final score hesaplayalım
    temp_finals = []
    for _, row in final_metrics_df.iterrows():
        pen, _ = calculate_continuous_penalties(row['mdd'], row['volatility'], row['confidence'])
        temp_finals.append(max(0.0, row['absolute_score'] - pen))
    final_metrics_df['temp_final'] = temp_finals

    # 6. Kategori İçi Percentile Ranking
    final_metrics_df['category_percentile'] = final_metrics_df.groupby('category')['temp_final'].rank(pct=True, ascending=True) * 100.0

    score_records = []
    for _, row in final_metrics_df.iterrows():
        abs_score = float(row['absolute_score'])
        conf = float(row['confidence'])
        mdd = float(row['mdd'])
        vol = float(row['volatility'])
        
        pen_total, pen_details = calculate_continuous_penalties(mdd, vol, conf)
        final_score = float(max(0.0, min(100.0, abs_score - pen_total)))
        percentile = float(row['category_percentile'])

        grade, signal = evaluate_rating_gate(final_score, percentile, conf)

        # 9. Explainability Engine (Açıklanabilirlik JSON)
        breakdown_dict = {
            "perf_component": round(float(row['perf_comp']), 2),
            "risk_component": round(float(row['risk_comp']), 2),
            "cashflow_component": round(float(row['cashflow_comp']), 2),
            "quality_component": round(float(row['quality_comp']), 2),
            "cost_component": round(float(row['cost_comp']), 2),
            "absolute_score": round(abs_score, 2),
            "penalties": pen_details,
            "total_penalty": round(pen_total, 2),
            "final_score": round(final_score, 2),
            "category_percentile": round(percentile, 2)
        }
        import json
        breakdown_json = json.dumps(breakdown_dict, ensure_ascii=False)

        score_records.append((
            int(row['fund_id']),
            today_str,
            abs_score,
            final_score,
            conf,
            percentile,
            signal,
            grade,
            breakdown_json
        ))

    cursor = conn.cursor()
    cursor.executemany("""
        INSERT OR REPLACE INTO fund_scores 
        (fund_id, date, absolute_score, final_score, confidence_score, category_percentile, signal, letter_grade, breakdown_json) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, score_records)
    conn.commit()

def safe_fetch(start_date, end_date, max_retries=3):
    for attempt in range(max_retries):
        try:
            df = tefas_crawler.fetch(start=start_date, end=end_date)
            return df
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
            return df[df['code'].isin(codes_subset)]
    except Exception as e:
        pass
    return None

def run_tefas_sync_and_scoring(full_sync=False, *args, **kwargs):
    if not TEFAS_LIB_READY:
        return False, "TEFAS kütüphanesi yüklü değil!"
    
    progress_bar = st.progress(0)
    status_container = st.empty()
    
    sync_mode_title = "Tam Senkronizasyon (500 Gün)" if full_sync else "Hızlı Güncelleme (Son 30 Gün)"
    labels = [
        f"TEFAS API Taranıyor ({'500 Gün' if full_sync else 'Son 30 Gün'})",
        "Fon Keşfi & Veritabanı Eşlemesi",
        "Geçmiş Fiyat Senkronizasyonu (Paralel Worker)",
        "Kompozit Faktör, Z-Score ve Sürekli Ceza Matrisi Çalıştırılıyor"
    ]
    
    def update_ui(statuses, detail=""):
        lines = [f"**Mimari Mod:** `{sync_mode_title}`\n"]
        icons = {0: "⏳", 1: "🔄", 2: "✅"}
        for idx, label in enumerate(labels):
            st_code = statuses[idx]
            if st_code == 1 and detail:
                lines.append(f"{icons[st_code]} {label}    **`{detail}`**")
            else:
                lines.append(f"{icons[st_code]} {label}")
        status_container.markdown("\n\n".join(lines))

    statuses = [1, 0, 0, 0]
    update_ui(statuses, "Piyasa taranıyor...")
    progress_bar.progress(10)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        existing_codes_df = pd.read_sql("SELECT code FROM funds", con=conn)
        existing_codes = set(existing_codes_df['code'].tolist()) if not existing_codes_df.empty else set()
        old_count = len(existing_codes)
        
        today = datetime.date.today()
        scan_days = 500 if full_sync else (35 if old_count == 0 else 30)
        recent_start = today - datetime.timedelta(days=scan_days)
        
        try:
            recent_df = safe_fetch(recent_start.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'))
        except Exception as e:
            return False, f"TEFAS API bağlantı hatası: {str(e)}"
            
        if recent_df is None or recent_df.empty:
            return False, "TEFAS API veri döndüremedi."
            
        progress_bar.progress(25)
        statuses = [2, 1, 0, 0]
        
        recent_df = recent_df.drop_duplicates(subset=['code', 'date'])
        all_fetched_codes = set(recent_df['code'].unique()) if 'code' in recent_df.columns else set()
        brand_new_codes = [c for c in sorted(list(all_fetched_codes)) if c not in existing_codes]
        
        allowed_codes = existing_codes.union(set(brand_new_codes))
        recent_df = recent_df[recent_df['code'].isin(allowed_codes)]
        
        for code in allowed_codes:
            match = recent_df[recent_df['code'] == code]
            title, category = code, "Diğer"
            if not match.empty:
                if 'title' in match.columns and pd.notna(match['title'].iloc[0]): title = match['title'].iloc[0]
                if 'category' in match.columns and pd.notna(match['category'].iloc[0]): category = match['category'].iloc[0]
            
            is_qual = detect_qualified_fund(title, category)
            cursor.execute("""
                INSERT INTO funds (code, title, category, status, is_qualified, history_completed) VALUES (?, ?, ?, 'ACTIVE', ?, 0)
                ON CONFLICT(code) DO UPDATE SET title=excluded.title, category=excluded.category, status='ACTIVE', is_qualified=excluded.is_qualified
            """, (code, title, category, is_qual))
            
        conn.commit()
        funds_map = pd.read_sql("SELECT id, code FROM funds", con=conn).set_index('code')['id'].to_dict()
        recent_df['fund_id'] = recent_df['code'].map(funds_map)
        recent_df = recent_df.dropna(subset=['fund_id'])
        
        price_records = [(int(row['fund_id']), str(row['date'])[:10], float(row['price'])) for _, row in recent_df.iterrows()]
        cursor.executemany("INSERT OR REPLACE INTO fund_daily_prices (fund_id, date, price) VALUES (?, ?, ?)", price_records)
        conn.commit()

        statuses = [2, 2, 1, 0]
        progress_bar.progress(60)
        
        if full_sync:
            needing_history = set(allowed_codes)
        else:
            incomplete_df = pd.read_sql("SELECT code FROM funds WHERE history_completed = 0", con=conn)
            needing_history = set(incomplete_df['code'].tolist())
        
        if needing_history:
            update_ui(statuses, f"{len(needing_history)} fon için geçmiş veri çekiliyor...")
            start_hist = today - datetime.timedelta(days=500)
            end_hist = today - datetime.timedelta(days=scan_days)
            
            tasks = []
            curr_start = start_hist
            while curr_start < end_hist:
                curr_end = min(curr_start + datetime.timedelta(days=180), end_hist)
                tasks.append((curr_start.strftime('%Y-%m-%d'), curr_end.strftime('%Y-%m-%d'), needing_history))
                curr_start = curr_end + datetime.timedelta(days=1)
                
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(fetch_chunk_worker, task) for task in tasks]
                for future in as_completed(futures):
                    chunk_df = future.result()
                    if chunk_df is not None and not chunk_df.empty:
                        chunk_df['fund_id'] = chunk_df['code'].map(funds_map)
                        chunk_df = chunk_df.dropna(subset=['fund_id'])
                        c_records = [(int(r['fund_id']), str(r['date'])[:10], float(r['price'])) for _, r in chunk_df.iterrows()]
                        cursor.executemany("INSERT OR REPLACE INTO fund_daily_prices (fund_id, date, price) VALUES (?, ?, ?)", c_records)
                        conn.commit()
                        
            completed_ids = [funds_map[code] for code in needing_history if code in funds_map]
            if completed_ids:
                cursor.executemany("UPDATE funds SET history_completed = 1 WHERE id = ?", [(fid,) for fid in completed_ids])
                conn.commit()

        statuses = [2, 2, 2, 1]
        update_ui(statuses, "Z-Score, Kompozit ve Sürekli Ceza motoru çalıştırılıyor...")
        progress_bar.progress(85)

        run_batch_scoring_engine(conn)

        sync_time_str = datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_sync', ?)", (sync_time_str,))
        conn.commit()
        
        total_after = len(pd.read_sql("SELECT id FROM funds", con=conn))
        
        statuses = [2, 2, 2, 2]
        update_ui(statuses, "Nihai Mimari Başarıyla Senkronize Edildi!")
        progress_bar.progress(100)
        
        return True, f"Başarılı! Toplam Fon: {total_after} | Yeni Nesil Kantitatif Matris Güncellendi."

    except Exception as e:
        return False, f"Hata: {str(e)}"
    finally:
        conn.close()
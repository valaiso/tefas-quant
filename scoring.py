import pandas as pd
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
            total_score REAL,
            confidence_score REAL,
            signal TEXT,
            letter_grade TEXT,
            PRIMARY KEY (fund_id, date)
        )
    """)
    
    # --- YENİ EKLENEN TABLOLAR (Fonların Gizli Cevherleri İçin) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT UNIQUE,
            name TEXT,
            sector TEXT,
            dcf_discount REAL,
            ev_ebitda REAL,
            pe_ratio REAL,
            pb_ratio REAL,
            fx_growth_score REAL,
            cagr_growth REAL,
            quant_score REAL,
            last_updated TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fund_stock_holdings (
            fund_id INTEGER,
            stock_id INTEGER,
            weight REAL,
            PRIMARY KEY (fund_id, stock_id)
        )
    """)
    # -------------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    migrations = [
        ("funds", "is_qualified INTEGER DEFAULT 0"),
        ("funds", "history_completed INTEGER DEFAULT 0"),
        ("fund_scores", "letter_grade TEXT"),
        ("fund_scores", "signal TEXT"),
        ("fund_scores", "confidence_score REAL")
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

def evaluate_signal_and_grade(score, confidence, day_count):
    if day_count < 15:
        return 'Yeni Fon (Kuluçkada)', 'Zayıf'

    if score >= 85 and confidence >= 65:
        signal = 'Güçlü AL'
        letter_grade = 'A+'
    elif score >= 75 and confidence >= 55:
        signal = 'AL / İzle'
        letter_grade = 'A'
    elif score >= 60:
        signal = 'Bekle'
        letter_grade = 'B'
    elif score >= 40:
        signal = 'Zayıf'
        letter_grade = 'C'
    else:
        signal = 'Uzak Dur'
        letter_grade = 'Zayıf'

    if confidence < 40 and signal in ['Güçlü AL', 'AL / İzle']:
        signal = 'Bekle'
        letter_grade = 'C'

    return signal, letter_grade

def calculate_confidence_and_score(p_history):
    day_count = len(p_history)
    if day_count == 0:
        return 0.0, 50.0, "Yeni Fon (Kuluçkada)", "Zayıf"

    prices = p_history['price'].values
    prices = prices[prices > 0]

    if len(prices) < 2:
        return 0.0, 0.0, "Yeni Fon (Kuluçkada)", "Zayıf"

    day_count = len(prices)

    r_30 = (prices[-1] / prices[-30] - 1) * 100 if day_count >= 30 else (prices[-1] / prices[0] - 1) * 100
    r_90 = (prices[-1] / prices[-90] - 1) * 100 if day_count >= 90 else r_30
    r_365 = (prices[-1] / prices[-365] - 1) * 100 if day_count >= 365 else r_90

    score_30 = min(max(50 + r_30 * 1.2, 0), 100)
    score_90 = min(max(50 + r_90 * 0.9, 0), 100)
    score_365 = min(max(50 + r_365 * 0.6, 0), 100)
    
    daily_returns = p_history['price'].pct_change().dropna()
    volatility = daily_returns.std() * (255 ** 0.5) if len(daily_returns) > 5 else 0.2
    stability_score = max(0, min(100, 100 - (volatility * 100)))

    raw_score = (score_30 * 0.25) + (score_90 * 0.30) + (score_365 * 0.25) + (stability_score * 0.20)

    age_score = min(100.0, (day_count / 365.0) * 100.0)
    expected_days = (pd.to_datetime(p_history['date'].iloc[-1]) - pd.to_datetime(p_history['date'].iloc[0])).days + 1
    density_score = min(100.0, (day_count / max(1, expected_days)) * 100.0) if expected_days > 0 else 100.0
    integrity_score = 100.0 if day_count > 30 else (day_count / 30.0) * 100.0
    
    last_date = pd.to_datetime(p_history['date'].iloc[-1])
    days_diff = (datetime.date.today() - last_date.date()).days
    recency_score = max(0.0, 100.0 - (days_diff * 5.0))

    confidence = (age_score * 0.35) + (density_score * 0.25) + (integrity_score * 0.20) + (recency_score * 0.10) + (stability_score * 0.10)
    confidence = min(100.0, max(10.0, confidence))

    penalty = (100.0 - confidence) * 0.12
    score = min(max(raw_score - penalty, 0), 100)

    signal, letter_grade = evaluate_signal_and_grade(score, confidence, day_count)

    return float(confidence), float(score), signal, letter_grade

def safe_fetch(start_date, end_date, max_retries=3):
    for attempt in range(max_retries):
        try:
            df = tefas_crawler.fetch(start=start_date, end=end_date)
            return df
        except Exception as e:
            if attempt < max_retries - 1:
                sleep_time = random.uniform(3.0, 6.0) * (attempt + 1)
                time.sleep(sleep_time)
            else:
                raise e
    return None

def fetch_chunk_worker(args):
    s_str, e_str, codes_subset = args
    try:
        time.sleep(random.uniform(0.5, 2.5))
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
        "Yeni Fon Keşfi & Veritabanı Eşlemesi",
        "Geçmiş Fiyat Senkronizasyonu (Paralel Worker / history_completed)",
        "Bellek İçi (In-Memory) Toplu Skor Matrisi Hesaplama"
    ]
    
    def update_ui(statuses, detail=""):
        lines = [f"**Mod:** `{sync_mode_title}`\n"]
        icons = {0: "⏳", 1: "🔄", 2: "✅"}
        for idx, label in enumerate(labels):
            st_code = statuses[idx]
            if st_code == 1 and detail:
                lines.append(f"{icons[st_code]} {label}    **`{detail}`**")
            else:
                lines.append(f"{icons[st_code]} {label}")
        status_container.markdown("\n\n".join(lines))

    statuses = [1, 0, 0, 0]
    update_ui(statuses, "Piyasa verileri taranıyor...")
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
        selected_new_codes = brand_new_codes[:100]
        new_funds_detected = len(selected_new_codes)
        
        update_ui(statuses, f"Mevcut: {old_count} | Yeni Algılanan Fon: +{new_funds_detected}")
        progress_bar.progress(40)
        
        allowed_codes = existing_codes.union(set(selected_new_codes))
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
            update_ui(statuses, f"{len(needing_history)} fon için geçmiş veriler çekiliyor...")
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
        else:
            update_ui(statuses, "Tüm fonların geçmişi tamamlanmış. Atlandı! 🚀")

        statuses = [2, 2, 2, 1]
        update_ui(statuses, "RAM'e veri yükleniyor ve matris hesaplanıyor...")
        progress_bar.progress(85)

        if full_sync:
            funds_to_score_ids = list(funds_map.values())
        else:
            affected_df = pd.read_sql(f"SELECT DISTINCT fund_id FROM fund_daily_prices WHERE date >= '{recent_start.strftime('%Y-%m-%d')}'", con=conn)
            funds_to_score_ids = affected_df['fund_id'].tolist() if not affected_df.empty else list(funds_map.values())

        if funds_to_score_ids:
            ids_str = ",".join(map(str, funds_to_score_ids))
            all_prices_df = pd.read_sql(f"""
                SELECT fund_id, date, price 
                FROM fund_daily_prices 
                WHERE fund_id IN ({ids_str}) 
                ORDER BY fund_id, date ASC
            """, con=conn)
            
            grouped_prices = dict(tuple(all_prices_df.groupby('fund_id')))
            end_date = today.strftime('%Y-%m-%d')
            score_records = []
            
            for f_id in funds_to_score_ids:
                if f_id in grouped_prices:
                    p_history = grouped_prices[f_id]
                    confidence, score, signal, letter_grade = calculate_confidence_and_score(p_history)
                    score_records.append((f_id, end_date, float(score), float(confidence), signal, letter_grade))

            cursor.executemany("""
                INSERT OR REPLACE INTO fund_scores (fund_id, date, total_score, confidence_score, signal, letter_grade) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, score_records)
            conn.commit()

        sync_time_str = datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_sync', ?)", (sync_time_str,))
        conn.commit()
        
        total_after = len(pd.read_sql("SELECT id FROM funds", con=conn))
        
        statuses = [2, 2, 2, 2]
        update_ui(statuses, "Tamamlandı!")
        progress_bar.progress(100)
        
        msg = f"Başarılı! Toplam Fon: {total_after} | Senkronize Edilen / Skorlanan: {len(funds_to_score_ids)} fon."
        return True, msg

    except Exception as e:
        return False, f"Hata: {str(e)}"
    finally:
        conn.close()
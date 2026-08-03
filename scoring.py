import pandas as pd
import sqlite3
import datetime
import os
import time
import streamlit as st

try:
    from tefas import Crawler
    tefas_crawler = Crawler(fund_limit=100)
    TEFAS_LIB_READY = True
except ImportError:
    TEFAS_LIB_READY = False

def get_db_connection():
    if os.path.exists("/mount/src"):
        db_path = "/tmp/tefas.db"
    else:
        db_path = "tefas.db"
    conn = sqlite3.connect(db_path, check_same_thread=False)
    
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS funds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            title TEXT,
            category TEXT,
            status TEXT DEFAULT 'ACTIVE',
            is_qualified INTEGER DEFAULT 0
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
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

    if score >= 90:
        signal = 'Güçlü AL'
    elif score >= 75:
        signal = 'AL / İzle'
    elif score >= 60:
        signal = 'Bekle'
    elif score >= 40:
        signal = 'Zayıf'
    else:
        signal = 'Uzak Dur'

    if score >= 90:
        letter_grade = 'A+'
    elif score >= 80:
        letter_grade = 'A'
    elif score >= 70:
        letter_grade = 'B'
    elif score >= 60:
        letter_grade = 'C'
    else:
        letter_grade = 'Zayıf'

    if confidence < 25:
        signal = 'Uzak Dur'
        letter_grade = 'Zayıf'
    elif confidence < 50:
        if signal in ['Güçlü AL', 'AL / İzle']:
            signal = 'Bekle'

    return signal, letter_grade

def calculate_confidence_and_score(p_history):
    day_count = len(p_history)
    if day_count == 0:
        return 0.0, 50.0, "Yeni Fon (Kuluçkada)", "Zayıf"

    prices = p_history['price'].values
    
    r_30 = (prices[-1] / prices[-30] - 1) * 100 if day_count >= 30 else (prices[-1] / prices[0] - 1) * 100
    r_90 = (prices[-1] / prices[-90] - 1) * 100 if day_count >= 90 else r_30
    r_365 = (prices[-1] / prices[-365] - 1) * 100 if day_count >= 365 else r_90

    score_30 = min(max(50 + r_30 * 1.5, 0), 100)
    score_90 = min(max(50 + r_90 * 1.0, 0), 100)
    score_365 = min(max(50 + r_365 * 0.5, 0), 100)
    
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

    confidence = (age_score * 0.40) + (density_score * 0.30) + (integrity_score * 0.20) + (recency_score * 0.10)
    confidence = min(100.0, max(0.0, confidence))

    def get_penalty(conf):
        if conf >= 95: return 0
        elif conf >= 90: return -1
        elif conf >= 80: return -2
        elif conf >= 70: return -3
        elif conf >= 60: return -5
        elif conf >= 50: return -7
        elif conf >= 40: return -10
        elif conf >= 30: return -13
        elif conf >= 20: return -17
        elif conf >= 10: return -22
        else: return -30

    penalty = get_penalty(confidence)
    score = min(max(raw_score + penalty, 0), 100)

    signal, letter_grade = evaluate_signal_and_grade(score, confidence, day_count)

    return float(confidence), float(score), signal, letter_grade

def run_tefas_sync_and_scoring():
    if not TEFAS_LIB_READY:
        return False, "TEFAS kütüphanesi yüklü değil!"
    
    progress_bar = st.progress(0)
    status_container = st.empty()
    
    labels = [
        "TEFAS API'den Güncel Veriler Çekiliyor (Maks 100 Fon - 5 Yıllık Dilimler)",
        "Fon Listesi ve Nitelikli Fon Tespiti Yapılıyor",
        "Eski ve Yeni Fiyat Geçmişleri / Tarihler Güncelleniyor",
        "100 Puanlık Kantitatif Skor ve Kalite Matrisi Hesaplanıyor"
    ]
    
    def update_ui(statuses, detail=""):
        lines = []
        icons = {0: "⏳", 1: "🔄", 2: "✅"}
        for idx, label in enumerate(labels):
            st_code = statuses[idx]
            if st_code == 1 and detail:
                lines.append(f"{icons[st_code]} {label} &nbsp;&nbsp; **`{detail}`**")
            else:
                lines.append(f"{icons[st_code]} {label}")
        status_container.markdown("\n\n".join(lines))

    statuses = [1, 0, 0, 0]
    update_ui(statuses, "Dilim 1/5 indiriliyor...")
    progress_bar.progress(5)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        existing_codes_df = pd.read_sql("SELECT code FROM funds", con=conn)
        existing_codes = set(existing_codes_df['code'].tolist()) if not existing_codes_df.empty else set()
        old_count = len(existing_codes)
        
        today = datetime.date.today()
        all_dfs = []
        
        for i in range(5):
            chunk_end = today - datetime.timedelta(days=i * 365)
            chunk_start = today - datetime.timedelta(days=(i + 1) * 365)
            
            update_ui(statuses, f"Yıl Dilimi {i+1}/5 indiriliyor...")
            try:
                df_chunk = tefas_crawler.fetch(start=chunk_start.strftime('%Y-%m-%d'), end=chunk_end.strftime('%Y-%m-%d'))
                if df_chunk is not None and not df_chunk.empty:
                    all_dfs.append(df_chunk)
            except Exception:
                pass
            
            # Rate-limit önlemi için istekler arası bekleme
            time.sleep(1.5)
            progress_bar.progress(int(5 + (i + 1) * 14))
            
        if not all_dfs:
            return False, "TEFAS API veri döndüremedi. (Sunucu yoğun olabilir, lütfen tekrar deneyin)."
            
        statuses = [2, 1, 0, 0]
        update_ui(statuses, "Fonlar taranıyor ve güncelleniyor...")
        progress_bar.progress(80)
        
        prices_df = pd.concat(all_dfs, ignore_index=True)
        prices_df = prices_df.drop_duplicates(subset=['code', 'date'])
        active_codes = prices_df['code'].unique() if 'code' in prices_df.columns else []
        
        new_funds_detected = 0
        total_active_codes = len(active_codes)
        
        for idx, code in enumerate(active_codes, 1):
            title, category = code, "Diğer"
            match = prices_df[prices_df['code'] == code]
            if not match.empty:
                if 'title' in match.columns: title = match['title'].iloc[0]
                if 'category' in match.columns: category = match['category'].iloc[0]
            
            is_qual = detect_qualified_fund(title, category)
            
            if code not in existing_codes:
                new_funds_detected += 1
            
            cursor.execute("""
                INSERT INTO funds (code, title, category, status, is_qualified) VALUES (?, ?, ?, 'ACTIVE', ?)
                ON CONFLICT(code) DO UPDATE SET title=excluded.title, category=excluded.category, status='ACTIVE', is_qualified=excluded.is_qualified
            """, (code, title, category, is_qual))
            
            if idx % 25 == 0 or idx == total_active_codes:
                update_ui(statuses, f"Fon Kaydı: ({idx}/{total_active_codes})")
                
        conn.commit()

        funds_map = pd.read_sql("SELECT id, code FROM funds", con=conn).set_index('code')['id'].to_dict()
        prices_df['fund_id'] = prices_df['code'].map(funds_map)
        prices_df = prices_df.dropna(subset=['fund_id'])
        
        statuses = [2, 2, 1, 0]
        update_ui(statuses, "Fiyat geçmişleri ve yeni tarihler işleniyor...")
        progress_bar.progress(90)
        
        for _, row in prices_df.iterrows():
            cursor.execute("INSERT OR REPLACE INTO fund_daily_prices (fund_id, date, price) VALUES (?, ?, ?)", 
                           (int(row['fund_id']), str(row['date'])[:10], float(row['price'])))
        conn.commit()

        statuses = [2, 2, 2, 1]
        update_ui(statuses, "100 Puanlık matris hesaplanıyor...")
        progress_bar.progress(95)

        all_funds = pd.read_sql("SELECT id, code FROM funds WHERE status = 'ACTIVE'", con=conn)
        total_funds_to_score = len(all_funds)
        end_date = today.strftime('%Y-%m-%d')
        
        for idx, (_, fund) in enumerate(all_funds.iterrows(), 1):
            f_id = int(fund['id'])
            p_history = pd.read_sql(f"SELECT date, price FROM fund_daily_prices WHERE fund_id = {f_id} ORDER BY date ASC", con=conn)
            confidence, score, signal, letter_grade = calculate_confidence_and_score(p_history)
            
            cursor.execute("""
                INSERT OR REPLACE INTO fund_scores (fund_id, date, total_score, confidence_score, signal, letter_grade) VALUES (?, ?, ?, ?, ?, ?)
            """, (f_id, end_date, float(score), float(confidence), signal, letter_grade))
            
            if idx % 10 == 0 or idx == total_funds_to_score:
                update_ui(statuses, f"Skorlanan: ({idx}/{total_funds_to_score}) fon")
                
        conn.commit()
        
        sync_time_str = datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_sync', ?)", (sync_time_str,))
        conn.commit()
        
        total_after = len(pd.read_sql("SELECT id FROM funds", con=conn))
        
        statuses = [2, 2, 2, 2]
        update_ui(statuses, "Tamamlandı!")
        progress_bar.progress(100)
        
        return True, f"Başarılı! Toplam Fon: {total_after} (Eski: {old_count} | Eklenen Yeni Fon: {new_funds_detected}). Tarihler ve veriler güncellendi."
    except Exception as e:
        return False, f"Hata: {str(e)}"
    finally:
        conn.close()
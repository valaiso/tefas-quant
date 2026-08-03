import pandas as pd
import sqlite3
import datetime
import os
import streamlit as st

try:
    from tefas import Crawler
    tefas_crawler = Crawler(fund_limit=1000)
    TEFAS_LIB_READY = True
except ImportError:
    TEFAS_LIB_READY = False

def get_db_connection():
    if os.path.exists("/mount/src"):
        db_path = "/tmp/tefas.db"
    else:
        db_path = "tefas.db"
    conn = sqlite3.connect(db_path, check_same_thread=False)
    
    # Tabloların var olduğundan emin olalım
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

def calculate_confidence_and_score(p_history):
    day_count = len(p_history)
    if day_count == 0:
        return 0.0, 50.0, "Yeni Fon (Kuluçkada)"

    age_score = min(100.0, (day_count / 365.0) * 100.0)
    expected_days = (pd.to_datetime(p_history['date'].iloc[-1]) - pd.to_datetime(p_history['date'].iloc[0])).days + 1
    density_score = min(100.0, (day_count / max(1, expected_days)) * 100.0) if expected_days > 0 else 100.0
    integrity_score = 100.0 if day_count > 30 else (day_count / 30.0) * 100.0
    
    last_date = pd.to_datetime(p_history['date'].iloc[-1])
    days_diff = (datetime.date.today() - last_date.date()).days
    recency_score = max(0.0, 100.0 - (days_diff * 5.0))

    confidence = (age_score * 0.40) + (density_score * 0.30) + (integrity_score * 0.20) + (recency_score * 0.10)
    confidence = min(100.0, max(0.0, confidence))

    returns_30d = (p_history['price'].iloc[-1] / p_history['price'].iloc[-30] - 1) * 100 if day_count >= 30 else 0
    raw_score = 50 + returns_30d * 2

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

    if day_count < 15:
        signal = 'Yeni Fon (Kuluçkada)'
    else:
        if score >= 85: signal = 'Güçlü AL'
        elif score >= 70: signal = 'AL / İzle'
        elif score <= 50: signal = 'Zayıf'
        else: signal = 'Bekle'

    if confidence < 25:
        if signal in ['Güçlü AL', 'AL / İzle']: signal = 'Bekle'
    elif confidence < 50:
        if signal == 'Güçlü AL': signal = 'AL / İzle'

    return float(confidence), float(score), signal

def run_tefas_sync_and_scoring():
    if not TEFAS_LIB_READY:
        return False, "TEFAS kütüphanesi yüklü değil!"
    
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 1. Mevcut veritabanındaki kayıtlı fon kodlarını öğrenelim (Eski fon sayısını takip etmek için)
        existing_codes_df = pd.read_sql("SELECT code FROM funds", con=conn)
        existing_codes = set(existing_codes_df['code'].tolist()) if not existing_codes_df.empty else set()
        old_count = len(existing_codes)
        
        today = datetime.date.today()
        all_dfs = []
        
        status_text.text("📡 TEFAS API'den güncel veriler çekiliyor...")
        
        for i in range(5):
            chunk_end = today - datetime.timedelta(days=i * 365)
            chunk_start = today - datetime.timedelta(days=(i + 1) * 365)
            
            status_text.text(f"⏳ Dönem Sorgulanıyor: {chunk_start.strftime('%d.%m.%Y')} - {chunk_end.strftime('%d.%m.%Y')} (Yıl dilimi {i+1}/5)")
            progress_bar.progress((i + 1) * 15)
            
            try:
                df_chunk = tefas_crawler.fetch(start=chunk_start.strftime('%Y-%m-%d'), end=chunk_end.strftime('%Y-%m-%d'))
                if df_chunk is not None and not df_chunk.empty:
                    all_dfs.append(df_chunk)
            except Exception:
                pass
            
        if not all_dfs:
            return False, "TEFAS API veri döndüremedi."
            
        status_text.text("🔄 Veriler işleniyor: Eski fonlar korunuyor, yeni fonlar ekleniyor ve tarihler güncelleniyor...")
        progress_bar.progress(80)
        
        prices_df = pd.concat(all_dfs, ignore_index=True)
        prices_df = prices_df.drop_duplicates(subset=['code', 'date'])
        active_codes = prices_df['code'].unique() if 'code' in prices_df.columns else []
        
        # KÜMÜLATİF EKLEME MANTIĞI: Eski fonları silmiyoruz, yenileri ekliyoruz veya güncelliyoruz.
        new_funds_detected = 0
        for code in active_codes:
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
        conn.commit()

        funds_map = pd.read_sql("SELECT id, code FROM funds", con=conn).set_index('code')['id'].to_dict()
        prices_df['fund_id'] = prices_df['code'].map(funds_map)
        prices_df = prices_df.dropna(subset=['fund_id'])
        
        status_text.text("💾 Fiyat geçmişi ve yeni tarihler veritabanına işleniyor...")
        progress_bar.progress(90)
        
        # INSERT OR REPLACE ile eski fiyatlar silinmez, yeni tarihler eklenir/güncellenir
        for _, row in prices_df.iterrows():
            cursor.execute("INSERT OR REPLACE INTO fund_daily_prices (fund_id, date, price) VALUES (?, ?, ?)", 
                           (int(row['fund_id']), str(row['date'])[:10], float(row['price'])))
        conn.commit()

        status_text.text("⚡ Tüm fonlar için skor ve güven matrisi güncelleniyor...")
        progress_bar.progress(95)

        all_funds = pd.read_sql("SELECT id, code FROM funds WHERE status = 'ACTIVE'", con=conn)
        end_date = today.strftime('%Y-%m-%d')
        
        for _, fund in all_funds.iterrows():
            f_id = int(fund['id'])
            p_history = pd.read_sql(f"SELECT date, price FROM fund_daily_prices WHERE fund_id = {f_id} ORDER BY date ASC", con=conn)
            confidence, score, signal = calculate_confidence_and_score(p_history)
            
            cursor.execute("""
                INSERT OR REPLACE INTO fund_scores (fund_id, date, total_score, confidence_score, signal) VALUES (?, ?, ?, ?, ?)
            """, (f_id, end_date, float(score), float(confidence), signal))
        conn.commit()
        
        sync_time_str = datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_sync', ?)", (sync_time_str,))
        conn.commit()
        
        total_after = len(pd.read_sql("SELECT id FROM funds", con=conn))
        
        progress_bar.progress(100)
        status_text.text("✅ Kümülatif senkronizasyon başarıyla tamamlandı!")
        
        return True, f"Başarılı! Toplam Fon: {total_after} (Eski: {old_count} | Eklenen Yeni Fon: {new_funds_detected}). Tarihler ve veriler güncellendi."
    except Exception as e:
        return False, f"Hata: {str(e)}"
    finally:
        conn.close()
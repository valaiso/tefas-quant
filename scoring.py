import pandas as pd
import sqlite3
import datetime
import os
import time
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
    
    migrations = [
        ("funds", "is_qualified INTEGER DEFAULT 0"),
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
        "TEFAS API'den Piyasa Verileri Taranıyor (Hızlı Keşif)",
        "Yeni Fon Keşfi (Maks 100 Yeni Fon) & Mevcut Fon Eşlemesi",
        "Eski ve Yeni Fiyat Geçmişleri Güncelleniyor (Hızlı Sync - 1.3 Yıl)",
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
    update_ui(statuses, "Piyasadaki aktif fonlar taranıyor...")
    progress_bar.progress(10)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 1. Veritabanındaki mevcut fon kodlarını al
        existing_codes_df = pd.read_sql("SELECT code FROM funds", con=conn)
        existing_codes = set(existing_codes_df['code'].tolist()) if not existing_codes_df.empty else set()
        old_count = len(existing_codes)
        
        today = datetime.date.today()
        recent_start = today - datetime.timedelta(days=35)
        
        # AŞAMA 1: Son 35 günlük hızlı veri çekerek tüm piyasayı tara
        try:
            recent_df = tefas_crawler.fetch(start=recent_start.strftime('%Y-%m-%d'), end=today.strftime('%Y-%m-%d'))
        except Exception as e:
            return False, f"TEFAS API bağlantı hatası: {str(e)}"
            
        if recent_df is None or recent_df.empty:
            return False, "TEFAS API veri döndüremedi."
            
        progress_bar.progress(25)
        statuses = [2, 1, 0, 0]
        
        recent_df = recent_df.drop_duplicates(subset=['code', 'date'])
        all_fetched_codes = set(recent_df['code'].unique()) if 'code' in recent_df.columns else set()
        
        # Veritabanında OLMAYAN yepyeni fonları bul (Maks 100 fon)
        brand_new_codes = [c for c in sorted(list(all_fetched_codes)) if c not in existing_codes]
        selected_new_codes = brand_new_codes[:100]
        new_funds_detected = len(selected_new_codes)
        
        update_ui(statuses, f"Eski Fonlar: {old_count} | Eklenen Yeni Fon: +{new_funds_detected}")
        progress_bar.progress(40)
        
        allowed_codes = existing_codes.union(set(selected_new_codes))
        recent_df = recent_df[recent_df['code'].isin(allowed_codes)]
        
        # 2. Fon tanımlarını kaydet/güncelle
        for code in allowed_codes:
            match = recent_df[recent_df['code'] == code]
            title, category = code, "Diğer"
            if not match.empty:
                if 'title' in match.columns and pd.notna(match['title'].iloc[0]): title = match['title'].iloc[0]
                if 'category' in match.columns and pd.notna(match['category'].iloc[0]): category = match['category'].iloc[0]
            
            is_qual = detect_qualified_fund(title, category)
            cursor.execute("""
                INSERT INTO funds (code, title, category, status, is_qualified) VALUES (?, ?, ?, 'ACTIVE', ?)
                ON CONFLICT(code) DO UPDATE SET title=excluded.title, category=excluded.category, status='ACTIVE', is_qualified=excluded.is_qualified
            """, (code, title, category, is_qual))
            
        conn.commit()

        funds_map = pd.read_sql("SELECT id, code FROM funds", con=conn).set_index('code')['id'].to_dict()
        recent_df['fund_id'] = recent_df['code'].map(funds_map)
        recent_df = recent_df.dropna(subset=['fund_id'])
        
        price_records = [(int(row['fund_id']), str(row['date'])[:10], float(row['price'])) for _, row in recent_df.iterrows()]
        cursor.executemany("INSERT OR REPLACE INTO fund_daily_prices (fund_id, date, price) VALUES (?, ?, ?)", price_records)
        conn.commit()

        # AŞAMA 2: Ultra Hızlı Geçmiş Senkronizasyonu (500 Gün / 180'er Günlük Parçalar)
        statuses = [2, 2, 1, 0]
        progress_bar.progress(60)
        
        # Veritabanında 60 günden az verisi olan fonları bul
        counts_df = pd.read_sql("SELECT f.code, COUNT(p.date) as cnt FROM funds f LEFT JOIN fund_daily_prices p ON f.id = p.fund_id GROUP BY f.code", con=conn)
        needing_history_codes = set(counts_df[counts_df['cnt'] < 60]['code'].tolist())
        
        if needing_history_codes:
            update_ui(statuses, f"{len(needing_history_codes)} yeni fon için 1.3 yıllık geçmiş indiriliyor...")
            
            # 5 yıl yerine 500 gün (1.3 yıl) çekiyoruz -> Skorlama için 365 gün yettiğinden %100 uyumlu
            start_hist = today - datetime.timedelta(days=500)
            end_hist = today - datetime.timedelta(days=30)
            
            curr_start = start_hist
            while curr_start < end_hist:
                curr_end = min(curr_start + datetime.timedelta(days=180), end_hist) # 90 gün yerine 180 gün
                s_str = curr_start.strftime('%Y-%m-%d')
                e_str = curr_end.strftime('%Y-%m-%d')
                
                update_ui(statuses, f"Geçmiş Veri Çekiliyor: {curr_start.strftime('%d.%m.%Y')} - {curr_end.strftime('%d.%m.%Y')}")
                
                try:
                    chunk_df = tefas_crawler.fetch(start=s_str, end=e_str)
                    if chunk_df is not None and not chunk_df.empty:
                        chunk_df = chunk_df[chunk_df['code'].isin(needing_history_codes)]
                        if not chunk_df.empty:
                            chunk_df['fund_id'] = chunk_df['code'].map(funds_map)
                            chunk_df = chunk_df.dropna(subset=['fund_id'])
                            c_records = [(int(r['fund_id']), str(r['date'])[:10], float(r['price'])) for _, r in chunk_df.iterrows()]
                            cursor.executemany("INSERT OR REPLACE INTO fund_daily_prices (fund_id, date, price) VALUES (?, ?, ?)", c_records)
                            conn.commit()
                except Exception as e:
                    print(f"⚠️ Parça çekme uyarısı ({s_str} - {e_str}): {e}")
                
                time.sleep(0.2) # Bekleme süresi 0.2 saniyeye indirildi
                curr_start = curr_end + datetime.timedelta(days=1)
        else:
            update_ui(statuses, "Tüm fonların geçmişi tam, sadece güncel fiyatlar güncellendi.")

        # AŞAMA 3: Skorlama Matrisi Hesaplama
        statuses = [2, 2, 2, 1]
        update_ui(statuses, "100 Puanlık matris hesaplanıyor...")
        progress_bar.progress(85)

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
            
            if idx % 50 == 0 or idx == total_funds_to_score:
                update_ui(statuses, f"Skorlanan: ({idx}/{total_funds_to_score}) fon")
                
        conn.commit()
        
        sync_time_str = datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_sync', ?)", (sync_time_str,))
        conn.commit()
        
        total_after = len(pd.read_sql("SELECT id FROM funds", con=conn))
        
        statuses = [2, 2, 2, 2]
        update_ui(statuses, "Tamamlandı!")
        progress_bar.progress(100)
        
        if new_funds_detected > 0:
            msg = f"Başarılı! Toplam Fon: {total_after} (Eski: {old_count} | Eklenen Yeni Fon: +{new_funds_detected}). Tüm fonlar senkronize edildi."
        else:
            msg = f"Başarılı! Yeni fon bulunamadı. Mevcut {total_after} fonun en güncel verileri ve skorları yenilendi."
            
        return True, msg
    except Exception as e:
        return False, f"Hata: {str(e)}"
    finally:
        conn.close()
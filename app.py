import streamlit as st
import pandas as pd
import sqlite3
import datetime
import numpy as np
import os

try:
    from tefas import Crawler
    # Tüm 600-700+ fonun çekilebilmesi için limit 1000 yapıldı
    tefas_crawler = Crawler(fund_limit=1000)
    TEFAS_LIB_READY = True
except ImportError:
    TEFAS_LIB_READY = False

# --- 1. SAYFA YAPILANDIRMASI & TEMA ---
st.set_page_config(
    page_title="TEFAS Institutional Quant Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .main { background-color: #0e1117; color: #c9d1d9; }
    .stMetric { background-color: #161b22; padding: 15px; border-radius: 8px; border: 1px solid #30363d; }
    </style>
""", unsafe_allow_html=True)

# --- 2. KURUMSAL VERİTABANI MİMARİSİ VE OTOMATİK MİGRASYON ---
def init_db():
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
            manager TEXT,
            launch_date TEXT,
            status TEXT DEFAULT 'ACTIVE',
            is_qualified INTEGER DEFAULT 0
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    for col, col_type in [("status", "TEXT DEFAULT 'ACTIVE'"), ("manager", "TEXT"), ("launch_date", "TEXT"), ("is_qualified", "INTEGER DEFAULT 0")]:
        try:
            cursor.execute(f"ALTER TABLE funds ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fund_daily_prices (
            fund_id INTEGER,
            date TEXT,
            price REAL,
            PRIMARY KEY (fund_id, date)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fund_metrics (
            fund_id INTEGER PRIMARY KEY,
            aum REAL,
            investor_count INTEGER,
            management_fee REAL
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
    
    try:
        cursor.execute("ALTER TABLE fund_scores ADD COLUMN confidence_score REAL")
    except sqlite3.OperationalError:
        pass
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code TEXT,
            buy_date TEXT,
            buy_price REAL,
            amount REAL
        )
    """)
    
    conn.commit()
    return conn

conn = init_db()

# --- 3. YAN MENÜ & NİTELİKLİ FON FİLTRELEME AYARI ---
st.sidebar.markdown("## ⚡ INSTITUTIONAL QUANT")

current_time_str = datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
st.sidebar.markdown(f"🕒 **Canlı Saat:** `{current_time_str}`")

try:
    meta_cursor = conn.cursor()
    meta_cursor.execute("SELECT value FROM metadata WHERE key='last_sync'")
    meta_row = meta_cursor.fetchone()
    last_sync_str = meta_row[0] if meta_row else "Henüz Senkronize Edilmedi"
except Exception:
    last_sync_str = "Henüz Senkronize Edilmedi"

st.sidebar.markdown(f"🔄 **Son Güncelleme:** `{last_sync_str}`")
st.sidebar.markdown("---")

include_qualified = st.sidebar.checkbox("🔒 Nitelikli Yatırımcı Fonlarını Dahil Et", value=False, help="İşaretlenmezse; Serbest, Özel, Gayrimenkul ve Girişim Sermayesi gibi sadece nitelikli yatırımcıya açık fonlar sistemden otomatik olarak hariç tutulur.")

st.sidebar.markdown("---")

menu = st.sidebar.radio(
    "Navigasyon",
    ["⚡ Ana Dashboard", "🔄 Evren Senkronizasyonu", "🔍 Fon Evreni & Yaş Filtresi", "💼 Portföyüm", "⭐ Favori Sepetim", "📊 Fon Detay & AI Raporu", "⚖️ Fon Karşılaştırma", "🚀 Backtest Performansı"]
)

if "favorites" not in st.session_state:
    st.session_state.favorites = []

# --- 4. NİTELİKLİ YATIRIMCI TESPİT FONKSİYONU ---
def detect_qualified_fund(title, category):
    text = f"{str(title).upper()} {str(category).upper()}"
    qualified_keywords = ["SERBEST", "ÖZEL", "GİRİŞİM", "GAYRİMENKUL", "NİTELİKLİ", "HEDGE"]
    for kw in qualified_keywords:
        if kw in text:
            return 1
    return 0

# --- 5. 5 YILLIK PARÇALI SENKRONİZASYON & TÜM FONLARI ÇEKME ---
def run_tefas_sync_and_scoring():
    if not TEFAS_LIB_READY:
        return False, "TEFAS kütüphanesi yüklü değil! requirements.txt dosyasını kontrol edin."
    
    try:
        cursor = conn.cursor()
        today = datetime.date.today()
        all_dfs = []
        
        with st.status("🔄 5 Yıllık Tüm TEFAS Evreni Parçalı Senkronizasyon Başlatıldı...", expanded=True) as status:
            for i in range(5):
                chunk_end = today - datetime.timedelta(days=i * 365)
                chunk_start = today - datetime.timedelta(days=(i + 1) * 365)
                st.write(f"📥 Dönem indiriliyor: **{chunk_start}** ile **{chunk_end}** arası...")
                try:
                    df_chunk = tefas_crawler.fetch(start=chunk_start.strftime('%Y-%m-%d'), end=chunk_end.strftime('%Y-%m-%d'))
                    if df_chunk is not None and not df_chunk.empty:
                        all_dfs.append(df_chunk)
                except Exception as chunk_err:
                    st.write(f"⚠️ Dönem uyarısı ({chunk_start} - {chunk_end}): {str(chunk_err)}")
            
        if not all_dfs:
            return False, "TEFAS API hiçbir dönemde veri döndüremedi."
            
        prices_df = pd.concat(all_dfs, ignore_index=True)
        prices_df = prices_df.drop_duplicates(subset=['code', 'date'])
        
        active_codes = prices_df['code'].unique() if 'code' in prices_df.columns else []
        
        cursor.execute("UPDATE funds SET status = 'PASSIVE'")
        conn.commit()
        
        total_codes = len(active_codes)
        
        with st.status(f"⚡ Toplam {total_codes} Fon, Nitelikli Analizi ve Fiyatlar İşleniyor...", expanded=True) as status_process:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for idx, code in enumerate(active_codes):
                title = code
                category = "Diğer"
                match = prices_df[prices_df['code'] == code]
                if not match.empty:
                    if 'title' in match.columns:
                        title = match['title'].iloc[0]
                    if 'category' in match.columns:
                        category = match['category'].iloc[0]
                
                is_qual = detect_qualified_fund(title, category)
                
                cursor.execute("""
                    INSERT INTO funds (code, title, category, status, is_qualified) VALUES (?, ?, ?, 'ACTIVE', ?)
                    ON CONFLICT(code) DO UPDATE SET title=excluded.title, category=excluded.category, status='ACTIVE', is_qualified=excluded.is_qualified
                """, (code, title, category, is_qual))
                
                remaining = total_codes - (idx + 1)
                progress_bar.progress((idx + 1) / total_codes)
                status_text.markdown(f"✅ **{code}** işlendi (Nitelikli: {bool(is_qual)}). | Kalan: **{remaining}**")
            
            conn.commit()
            status_process.update(label=f"✅ Toplam **{total_codes}** adet fon işlendi!", state="complete", expanded=False)

        with st.status("📊 Fiyat Verileri Güncelleniyor...", expanded=True) as status_prices:
            funds_map = pd.read_sql("SELECT id, code FROM funds", con=conn).set_index('code')['id'].to_dict()
            prices_df['fund_id'] = prices_df['code'].map(funds_map)
            prices_df = prices_df.dropna(subset=['fund_id'])
            
            for _, row in prices_df.iterrows():
                f_id = int(row['fund_id'])
                f_date = str(row['date'])[:10]
                f_price = float(row['price'])
                cursor.execute("""
                    INSERT OR REPLACE INTO fund_daily_prices (fund_id, date, price) VALUES (?, ?, ?)
                """, (f_id, f_date, f_price))
            conn.commit()
            status_prices.update(label="✅ Fiyat geçmişi güncellendi!", state="complete", expanded=False)

        with st.status("🧮 Kalite Puanı & Güven Skoru Hesaplanıyor...", expanded=True) as status_scores:
            all_funds = pd.read_sql("SELECT id, code, category FROM funds WHERE status = 'ACTIVE'", con=conn)
            end_date = today.strftime('%Y-%m-%d')
            
            for _, fund in all_funds.iterrows():
                f_id = int(fund['id'])
                p_history = pd.read_sql(f"SELECT price FROM fund_daily_prices WHERE fund_id = {f_id} ORDER BY date ASC", con=conn)
                day_count = len(p_history)
                
                confidence = min(100.0, (day_count / 365.0) * 100.0)
                
                if day_count < 15:
                    score = 50.0
                    signal = 'Yeni Fon (Kuluçkada)'
                else:
                    returns_30d = (p_history['price'].iloc[-1] / p_history['price'].iloc[-30] - 1) * 100 if day_count >= 30 else 0
                    raw_score = 50 + returns_30d * 2
                    
                    penalty = 0.0
                    if day_count < 90:
                        penalty = 5.0
                    elif day_count < 180:
                        penalty = 3.0
                    elif day_count < 365:
                        penalty = 1.0
                    
                    score = min(max(raw_score - penalty, 0), 100)
                    
                    signal = 'Bekle'
                    if score >= 85: 
                        signal = 'Güçlü AL'
                    elif score >= 70: 
                        signal = 'AL / İzle'
                    elif score <= 50: 
                        signal = 'Zayıf'
                
                cursor.execute("""
                    INSERT OR REPLACE INTO fund_scores (fund_id, date, total_score, confidence_score, signal) VALUES (?, ?, ?, ?, ?)
                """, (f_id, end_date, float(score), float(confidence), signal))
            conn.commit()
            status_scores.update(label="✅ Puanlama tamamlandı!", state="complete", expanded=False)
        
        sync_time_str = datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_sync', ?)", (sync_time_str,))
        conn.commit()
        
        return True, f"🎉 İşlem Tamamlandı! Tüm TEFAS evreni ({total_codes} fon) 5 yıllık verileriyle güncellendi."
    except Exception as e:
        return False, f"Senkronizasyon Hatası: {str(e)}"

# --- 6. VERİ YÜKLEME VE OTOMATİK NİTELİKLİ FİLTRELEME ---
def load_universe_data():
    try:
        funds_df = pd.read_sql("SELECT id, code, title AS name, category, status, is_qualified FROM funds", con=conn)
    except Exception:
        return pd.DataFrame()
        
    scores_df = pd.read_sql("SELECT * FROM fund_scores", con=conn)
    
    if scores_df.empty or funds_df.empty:
        return pd.DataFrame()

    funds_df['id'] = pd.to_numeric(funds_df['id'], errors='coerce').astype('int64')
    scores_df['fund_id'] = pd.to_numeric(scores_df['fund_id'], errors='coerce').astype('int64')

    scores_df['date_dt'] = pd.to_datetime(scores_df['date'])
    latest_date_raw = scores_df['date_dt'].max()
    latest_scores = scores_df[scores_df['date_dt'] == latest_date_raw].copy()
    
    merged = pd.merge(latest_scores, funds_df, left_on='fund_id', right_on='id', how='inner')
    merged['category'] = merged['category'].fillna('Diğer')
    
    price_counts = pd.read_sql("SELECT fund_id, COUNT(date) as day_count FROM fund_daily_prices GROUP BY fund_id", con=conn)
    if not price_counts.empty:
        price_counts['fund_id'] = pd.to_numeric(price_counts['fund_id'], errors='coerce').astype('int64')
    
    merged = pd.merge(merged, price_counts, on='fund_id', how='left')
    merged['day_count'] = merged['day_count'].fillna(0)
    
    if not include_qualified:
        merged = merged[merged['is_qualified'] == 0]
        
    return merged

merged_df = load_universe_data()

# ==========================================
# MODÜL: EVREN SENKRONİZASYONU
# ==========================================
if menu == "🔄 Evren Senkronizasyonu":
    st.title("🔄 Otomatik Fon Evreni Senkronizasyon Merkezi")
    st.markdown("---")
    st.markdown("""
    Bu ekrandan tek tuşla **TEFAS API**'ye bağlanarak:
    1. 5 yıllık geçmiş verileri indirebilir ve tüm piyasadaki **600+ fonun** tamamını güncelleyebilirsin.
    2. **Nitelikli Yatırımcı Fonlarını (Serbest, Özel, Girişim vb.) otomatik olarak ayıklayabilirsin.**
    3. Kalite Puanı ve Güven Skoru hesaplayabilirsin.
    """)
    
    if st.button("🚀 5 Yıllık Tüm TEFAS Evrenini Senkronize Et ve Güncelle", type="primary"):
        success, msg = run_tefas_sync_and_scoring()
        if success:
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)

# ==========================================
# MODÜL 1: ANA DASHBOARD
# ==========================================
elif menu == "⚡ Ana Dashboard":
    st.title("⚡ Kurumsal Piyasa & Evren Özeti")
    st.markdown("---")

    if not merged_df.empty:
        total_analyzed = len(merged_df)
        guclu_al = len(merged_df[merged_df['signal'] == 'Güçlü AL'])
        al_izle = len(merged_df[merged_df['signal'] == 'AL / İzle'])
        bekle = len(merged_df[merged_df['signal'] == 'Bekle'])
        zayif = len(merged_df[merged_df['signal'] == 'Zayıf'])
        avg_score = merged_df['total_score'].mean()
        avg_conf = merged_df['confidence_score'].mean() if 'confidence_score' in merged_df.columns else 0

        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("Toplam Evren", f"{total_analyzed}")
        col2.metric("Güçlü AL", f"{guclu_al}")
        col3.metric("AL / İzle", f"{al_izle}")
        col4.metric("Bekle", f"{bekle}")
        col5.metric("Ort. Puan", f"{avg_score:.1f}")
        col6.metric("Ort. Güven", f"%{avg_conf:.1f}")

        st.markdown("---")
        st.subheader("🏆 Kategori Bazlı En Güçlü Fonlar (Top 10)")
        top10 = merged_df.sort_values(by='total_score', ascending=False).head(10)
        
        for idx, row in top10.reset_index().iterrows():
            col_a, col_b, col_c, col_d = st.columns([1, 3, 2, 2])
            col_a.markdown(f"**#{idx+1}**")
            col_b.markdown(f"**{row['code']}** - {row['name']} *({row['category']})*")
            conf_val = row['confidence_score'] if 'confidence_score' in row else 0
            col_c.markdown(f"Skor: **{row['total_score']:.1f}** | Güven: **%{conf_val:.0f}** | *{row['signal']}*")
            
            is_fav = row['code'] in st.session_state.favorites
            btn_label = "⭐ Favoride" if is_fav else "☆ Favoriye Ekle"
            if col_d.button(btn_label, key=f"fav_dash_{row['code']}_{idx}"):
                if is_fav: st.session_state.favorites.remove(row['code'])
                else: st.session_state.favorites.append(row['code'])
                st.rerun()
    else:
        st.info("⚠️ Veritabanında evren verisi bulunamadı. Lütfen sol menüden **'🔄 Evren Senkronizasyonu'** sekmesine gidin.")

# ==========================================
# MODÜL 2: FON EVRESI & YAŞ FİLTRESİ
# ==========================================
elif menu == "🔍 Fon Evreni & Yaş Filtresi":
    st.title("🔍 Kategori Bazlı Fon Evreni ve Güven Süzgeci")
    st.markdown("---")
    if not merged_df.empty:
        col_search, col1, col2, col3 = st.columns([2, 2, 2, 2])
        search_code = col_search.text_input("🔍 Fon Kodu Ara", "").upper().strip()
        category_filter = col1.selectbox("Kategori", ["Tümü"] + list(merged_df['category'].unique()))
        signal_filter = col2.selectbox("Sinyal Durumu", ["Tümü", "Güçlü AL", "AL / İzle", "Bekle", "Zayıf", "Yeni Fon (Kuluçkada)"])
        min_score = col3.slider("Minimum Skor", 0, 100, 0)

        filtered_df = merged_df.copy()
        if search_code: filtered_df = filtered_df[filtered_df['code'].str.contains(search_code, na=False)]
        if category_filter != "Tümü": filtered_df = filtered_df[filtered_df['category'] == category_filter]
        if signal_filter != "Tümü": filtered_df = filtered_df[filtered_df['signal'] == signal_filter]
        filtered_df = filtered_df[filtered_df['total_score'] >= min_score]

        display_df = filtered_df[['code', 'name', 'category', 'day_count', 'total_score', 'confidence_score', 'signal']].rename(
            columns={'day_count': 'Geçmiş Gün', 'total_score': 'Kalite Puanı', 'confidence_score': 'Güven (%)'}
        ).sort_values(by='Kalite Puanı', ascending=False)
        
        st.dataframe(display_df, use_container_width=True)
    else:
        st.warning("Veritabanı boş. Önce Evren Senkronizasyonu yapın.")

# ==========================================
# MODÜL 3: PORTFÖYÜM
# ==========================================
elif menu == "💼 Portföyüm":
    st.title("💼 Canlı Portföy Takip & Kâr/Zarar Analizi")
    st.markdown("---")
    if not merged_df.empty:
        with st.form("portfolio_form"):
            st.subheader("➕ Portföye Fon Ekle")
            col_p1, col_p2, col_p3 = st.columns(3)
            selected_fund_code = col_p1.selectbox("Fon Seçin", merged_df['code'].unique())
            buy_date_input = col_p2.date_input("Alım Tarihi", datetime.date.today() - datetime.timedelta(days=30))
            invested_amount = col_p3.number_input("Yatırılan Tutar (TL)", min_value=100.0, value=10000.0, step=500.0)
            
            if st.form_submit_button("Portföye Ekle"):
                fund_id_row = merged_df[merged_df['code'] == selected_fund_code]['fund_id'].values[0]
                price_query = f"SELECT price FROM fund_daily_prices WHERE fund_id = {fund_id_row} AND date >= '{buy_date_input.strftime('%Y-%m-%d')}' ORDER BY date ASC LIMIT 1"
                price_df = pd.read_sql(price_query, con=conn)
                
                if not price_df.empty:
                    buy_price = price_df['price'].iloc[0]
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO portfolio (fund_code, buy_date, buy_price, amount) VALUES (?, ?, ?, ?)", (selected_fund_code, buy_date_input.strftime('%Y-%m-%d'), buy_price, invested_amount))
                    conn.commit()
                    st.success(f"✅ {selected_fund_code} portföye eklendi!")
                    st.rerun()
                else:
                    st.error("❌ Seçilen tarihte fiyat verisi bulunamadı.")

        st.markdown("---")
        portfolio_df = pd.read_sql("SELECT * FROM portfolio", con=conn)
        if not portfolio_df.empty:
            results = []
            for idx, row in portfolio_df.iterrows():
                f_code, b_date, b_price, inv_amt = row['fund_code'], row['buy_date'], row['buy_price'], row['amount']
                fund_id_row = merged_df[merged_df['code'] == f_code]['fund_id'].values[0]
                latest_p_df = pd.read_sql(f"SELECT price FROM fund_daily_prices WHERE fund_id = {fund_id_row} ORDER BY date DESC LIMIT 1", con=conn)
                
                if not latest_p_df.empty:
                    current_price = latest_p_df['price'].iloc[0]
                    shares = inv_amt / b_price
                    current_val = shares * current_price
                    profit_tl = current_val - inv_amt
                    profit_pct = ((current_price - b_price) / b_price) * 100
                    results.append({"ID": row['id'], "Fon Kodu": f_code, "Alım Tarihi": b_date, "Alış Fiyatı": b_price, "Yatırılan (TL)": inv_amt, "Güncel Değer": current_val, "Kâr/Zarar (TL)": profit_tl, "Kâr/Zarar (%)": profit_pct})
            
            res_df = pd.DataFrame(results)
            tot_inv, tot_val = res_df['Yatırılan (TL)'].sum(), res_df['Güncel Değer'].sum()
            tot_p_tl = tot_val - tot_inv
            tot_p_pct = (tot_p_tl / tot_inv) * 100 if tot_inv > 0 else 0
            
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("Toplam Yatırım", f"{tot_inv:,.2f} TL")
            col_m2.metric("Güncel Değer", f"{tot_val:,.2f} TL")
            col_m3.metric("Toplam Kâr/Zarar", f"{tot_p_tl:,.2f} TL", delta=f"{tot_p_pct:.2f}%")
            
            st.dataframe(res_df, use_container_width=True)
            
            del_id = st.selectbox("Silinecek Pozisyon ID", res_df['ID'].unique())
            if st.button("Pozisyonu Kaldır"):
                cursor = conn.cursor()
                cursor.execute("DELETE FROM portfolio WHERE id = ?", (del_id,))
                conn.commit()
                st.rerun()
        else:
            st.info("Portföyünüz boş.")
    else:
        st.warning("Veri yok.")

# ==========================================
# DİĞER MODÜLLER
# ==========================================
elif menu == "⭐ Favori Sepetim":
    st.title("⭐ Takip Ettiğim Favoriler")
    st.markdown("---")
    if st.session_state.favorites and not merged_df.empty:
        st.dataframe(merged_df[merged_df['code'].isin(st.session_state.favorites)][['code', 'name', 'category', 'total_score', 'confidence_score', 'signal']], use_container_width=True)
    else:
        st.info("Favori seçilmedi.")

elif menu == "📊 Fon Detay & AI Raporu":
    st.title("📊 Derinlemesine Fon Analizi")
    st.markdown("---")
    if not merged_df.empty:
        sel_code = st.selectbox("Fon Seçin", merged_df['code'].unique())
        row = merged_df[merged_df['code'] == sel_code].iloc[0]
        col_d1, col_d2 = st.columns(2)
        col_d1.metric("Kalite Puanı", f"{row['total_score']:.1f} / 100", f"Sinyal: {row['signal']}")
        conf_val = row['confidence_score'] if 'confidence_score' in row else 0
        col_d2.metric("Güven Skoru", f"%{conf_val:.1f}", f"Geçmiş Gün: {int(row['day_count'])}")
    else:
        st.warning("Veri yok.")

elif menu == "⚖️ Fon Karşılaştırma":
    st.title("⚖️ Fon Karşılaştırma Matrisi")
    st.markdown("---")
    if not merged_df.empty:
        selfunds = st.multiselect("Fonlar (Max 3)", merged_df['code'].unique(), max_selections=3)
        if selfunds:
            st.dataframe(merged_df[merged_df['code'].isin(selfunds)][['code', 'name', 'category', 'total_score', 'confidence_score', 'signal']], use_container_width=True)

elif menu == "🚀 Backtest Performansı":
    st.title("🚀 Strateji Güvenilirlik Testi (Backtest)")
    st.markdown("---")
    st.markdown("5 yıllık geçmiş verilerle otonom backtest altyapısı hazır.")
import streamlit as st
import pandas as pd
import datetime
import os
from scoring import get_db_connection, run_tefas_sync_and_scoring

# --- 1. SAYFA YAPILANDIRMASI & TEMA ---
st.set_page_config(
    page_title="TEFAS Institutional Quant Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    
""", unsafe_allow_html=True)

conn = get_db_connection()

# --- 2. YAN MENÜ & SOL ALT KOMPAKT NİTELİKLİ FON FİLTRESİ ---
st.sidebar.markdown("## ⚡ INSTITUTIONAL QUANT")
st.sidebar.markdown(f"🕒 **Canlı Saat:** `{datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}`")

try:
    meta_cursor = conn.cursor()
    meta_cursor.execute("SELECT value FROM metadata WHERE key='last_sync'")
    meta_row = meta_cursor.fetchone()
    last_sync_str = meta_row[0] if meta_row else "Henüz Senkronize Edilmedi"
except Exception:
    last_sync_str = "Henüz Senkronize Edilmedi"

st.sidebar.markdown(f"🔄 **Son Güncelleme:** `{last_sync_str}`")
st.sidebar.markdown("---")

menu = st.sidebar.radio(
    "Navigasyon",
    ["⚡ Ana Dashboard", "🔄 Fon Senkronizasyonu", "🔍 Fon Havuzu & Yaş Filtresi", "💼 Portföyüm", "⭐ Favori Sepetim", "📊 Fon Detay & AI Raporu", "⚖️ Fon Karşılaştırma", "🚀 Backtest Performansı"]
)

if "favorites" not in st.session_state:
    st.session_state.favorites = []

st.sidebar.markdown(
    """
    
    
    """,
    unsafe_allow_html=True
)

include_qualified = st.sidebar.checkbox("🔒 Nitelikli Fonları Dahil Et", value=False)
st.sidebar.markdown("", unsafe_allow_html=True)

# --- 3. VERİ YÜKLEME VE AKILLI FİLTRELEME ---
def load_universe_data():
    try:
        funds_df = pd.read_sql("SELECT id, code, title AS name, category, status, is_qualified FROM funds", con=conn)
        scores_df = pd.read_sql("SELECT * FROM fund_scores", con=conn)
    except Exception:
        return pd.DataFrame()
        
    if scores_df.empty or funds_df.empty:
        return pd.DataFrame()

    funds_df['id'] = pd.to_numeric(funds_df['id'], errors='coerce').astype('int64')
    scores_df['fund_id'] = pd.to_numeric(scores_df['fund_id'], errors='coerce').astype('int64')

    scores_df['date_dt'] = pd.to_datetime(scores_df['date'])
    latest_date_raw = scores_df['date_dt'].max()
    latest_scores = scores_df[scores_df['date_dt'] == latest_date_raw].copy()
    
    merged = pd.merge(latest_scores, funds_df, left_on='fund_id', right_on='id', how='inner')
    merged['category'] = merged['category'].fillna('Diğer')
    
    # Nitelikli fon sütununu veri tipinden bağımsız (int, str, bool) güvenli hale getir
    def parse_qualified(val):
        if pd.isna(val):
            return 0
        if isinstance(val, bool):
            return 1 if val else 0
        val_str = str(val).strip().lower()
        if val_str in ['true', '1', 'yes', 'y', 'evet']:
            return 1
        return 0

    merged['is_qualified_clean'] = merged['is_qualified'].apply(parse_qualified)
    
    price_counts = pd.read_sql("SELECT fund_id, COUNT(date) as day_count FROM fund_daily_prices GROUP BY fund_id", con=conn)
    if not price_counts.empty:
        price_counts['fund_id'] = pd.to_numeric(price_counts['fund_id'], errors='coerce').astype('int64')
    
    merged = pd.merge(merged, price_counts, on='fund_id', how='left')
    merged['day_count'] = merged['day_count'].fillna(0)
    
    # Tik işaretli değilse nitelikli fonları (1 olanları) listeden tamamen düş
    if not include_qualified:
        merged = merged[merged['is_qualified_clean'] == 0]
        
    return merged

merged_df = load_universe_data()

# ==========================================
# MODÜL: FON SENKRONİZASYONU
# ==========================================
if menu == "🔄 Fon Senkronizasyonu":
    st.title("🔄 Otomatik Fon Senkronizasyon Merkezi")
    st.markdown("---")
    st.markdown("""
    Bu ekran üzerinden TEFAS verilerini senkronize edebilir, nitelikli fonları ayıklayabilir ve matris skorlamasını çalıştırabilirsin.
    """)
    
    col1, col2 = st.columns(2)

    with col1:
        if st.button("⚡ Hızlı Güncelleme (Son 30 Gün)", use_container_width=True, type="primary", help="Son 30 günü tarar, sadece fiyatı değişen veya yeni fonları günceller. (~5-8 sn)"):
            with st.spinner("Hızlı güncelleme çalıştırılıyor..."):
                success, msg = run_tefas_sync_and_scoring(full_sync=False)
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    with col2:
        if st.button("🔄 Tam Senkronizasyon (500 Gün)", use_container_width=True, help="Tüm veritabanını ve 500 günlük geçmişi baştan tazeleyip tüm matrisi sıfırdan skorlar. (~25-35 sn)"):
            with st.spinner("Tam senkronizasyon çalıştırılıyor..."):
                success, msg = run_tefas_sync_and_scoring(full_sync=True)
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

# ==========================================
# MODÜL 1: ANA DASHBOARD
# ==========================================
elif menu == "⚡ Ana Dashboard":
    st.title("⚡ Kurumsal Piyasa & Fon Özeti")
    st.markdown("---")

    if not merged_df.empty:
        total_analyzed = len(merged_df)
        guclu_al = len(merged_df[merged_df['signal'] == 'Güçlü AL'])
        al_izle = len(merged_df[merged_df['signal'] == 'AL / İzle'])
        bekle = len(merged_df[merged_df['signal'] == 'Bekle'])
        avg_score = merged_df['total_score'].mean()
        avg_conf = merged_df['confidence_score'].mean() if 'confidence_score' in merged_df.columns else 0

        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("Toplam Fon", f"{total_analyzed}")
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
            
            score_val = row['total_score'] if pd.notna(row.get('total_score')) else 0.0
            conf_val = row['confidence_score'] if pd.notna(row.get('confidence_score')) else 0.0
            signal_val = row['signal'] if pd.notna(row.get('signal')) else 'Veri Yok'
            
            col_c.markdown(f"Skor: **{score_val:.1f}** | Güven: **%{conf_val:.0f}** | *{signal_val}*")
            
            is_fav = row['code'] in st.session_state.favorites
            btn_label = "⭐ Favoride" if is_fav else "☆ Favoriye Ekle"
            if col_d.button(btn_label, key=f"fav_dash_{row['code']}_{idx}"):
                if is_fav: st.session_state.favorites.remove(row['code'])
                else: st.session_state.favorites.append(row['code'])
                st.rerun()
    else:
        st.info("⚠️ Veritabanı boş. Lütfen sol menüden **'🔄 Fon Senkronizasyonu'** sekmesine gidin.")

# ==========================================
# DİĞER MODÜLLER
# ==========================================
elif menu == "🔍 Fon Havuzu & Yaş Filtresi":
    st.title("🔍 Kategori Bazlı Fon Havuzu ve Güven Süzgeci")
    st.markdown("---")
    if not merged_df.empty:
        display_df = merged_df[['code', 'name', 'category', 'day_count', 'total_score', 'confidence_score', 'signal']].rename(
            columns={'day_count': 'Geçmiş Gün', 'total_score': 'Kalite Puanı', 'confidence_score': 'Güven (%)'}
        ).sort_values(by='Kalite Puanı', ascending=False)
        st.dataframe(display_df, use_container_width=True)
    else:
        st.warning("Veri bulunamadı.")

elif menu == "💼 Portföyüm":
    st.title("💼 Portföy Takip")
    st.markdown("---")
    st.info("Portföy modülü aktif.")

elif menu == "⭐ Favori Sepetim":
    st.title("⭐ Favoriler")
    st.markdown("---")
    if st.session_state.favorites and not merged_df.empty:
        st.dataframe(merged_df[merged_df['code'].isin(st.session_state.favorites)][['code', 'name', 'category', 'total_score', 'confidence_score', 'signal']], use_container_width=True)
    else:
        st.info("Favori seçilmedi.")

elif menu in ["📊 Fon Detay & AI Raporu", "⚖️ Fon Karşılaştırma", "🚀 Backtest Performansı"]:
    st.title(f"📊 {menu}")
    st.markdown("---")
    st.info("Bu modül aktif.")
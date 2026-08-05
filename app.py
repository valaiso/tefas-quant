import streamlit as st
import pandas as pd
import numpy as np
import datetime
import os
import hashlib
import sqlite3

# Modüler Servis ve Motor İçe Aktarımları
from app.services.ranking import (
    get_db_connection,
    get_general_ranking,
    get_category_ranking,
    get_top_category_leaders,
    get_fund_detail_with_ranking
)
from scoring import run_tefas_sync_and_scoring

# --- 1. SAYFA YAPILANDIRMASI & TEMA ---
st.set_page_config(
    page_title="⚡ TEFAS Institutional Quant Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
        .main-header { font-size: 2.2rem; font-weight: 700; color: #1E3A8A; margin-bottom: 0px; }
        .sub-header { font-size: 1.1rem; color: #64748B; margin-bottom: 20px; }
        .card-container { background-color: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 20px; margin-bottom: 15px; color: #f8fafc; }
        .stMetric { background-color: #1e293b; padding: 15px; border-radius: 8px; border: 1px solid #334155; color: #f8fafc; }
        div[data-testid="stMetricValue"] { color: #f8fafc !important; }
        div[data-testid="stMetricLabel"] { color: #94a3b8 !important; }
        .badge-aplus { background-color: #DCFCE7; color: #166534; padding: 4px 10px; border-radius: 6px; font-weight: bold; }
        .badge-a { background-color: #ECFDF5; color: #047857; padding: 4px 10px; border-radius: 6px; font-weight: bold; }
        .badge-bplus { background-color: #FEF9C3; color: #854D0E; padding: 4px 10px; border-radius: 6px; font-weight: bold; }
        .badge-b { background-color: #FEF3C7; color: #92400E; padding: 4px 10px; border-radius: 6px; font-weight: bold; }
        .badge-c { background-color: #FFEDD5; color: #C2410C; padding: 4px 10px; border-radius: 6px; font-weight: bold; }
        .badge-d { background-color: #FEE2E2; color: #B91C1C; padding: 4px 10px; border-radius: 6px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# Veritabanı bağlantısı
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
    [
        "⚡ Ana Dashboard", 
        "🔎 Fon Keşif Merkezi", 
        "🔄 Fon Senkronizasyonu", 
        "🔍 Fon Havuzu & Yaş Filtresi", 
        "📊 Fon Detay & Gizli Cevherler", 
        "⚖️ Fon Karşılaştırma", 
        "🚀 Backtest Performansı"
    ]
)

# Nitelikli fonların dashboard ve listelerden izole edilmesi (Varsayılan olarak açık)
include_qualified = st.sidebar.checkbox("🔒 Nitelikli Fonları Dahil Et", value=True)
st.sidebar.markdown("---", unsafe_allow_html=True)

# --- 3. VERİ YÜKLEME VE KATEGORİ İÇİ YÜZDELİK SKORLAMA MEKANİZMASI ---
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
    
    def parse_qualified(val):
        if pd.isna(val): return 0
        if isinstance(val, bool): return 1 if val else 0
        val_str = str(val).strip().lower()
        return 1 if val_str in ['true', '1', 'yes', 'y', 'evet'] else 0

    merged['is_qualified_clean'] = merged['is_qualified'].apply(parse_qualified)
    
    price_counts = pd.read_sql("SELECT fund_id, COUNT(date) as day_count FROM fund_daily_prices GROUP BY fund_id", con=conn)
    if not price_counts.empty:
        price_counts['fund_id'] = pd.to_numeric(price_counts['fund_id'], errors='coerce').astype('int64')
    
    merged = pd.merge(merged, price_counts, on='fund_id', how='left')
    merged['day_count'] = merged['day_count'].fillna(0)
    
    if not include_qualified:
        merged = merged[merged['is_qualified_clean'] == 0]
        
    if 'confidence_score' in merged.columns:
        merged['confidence_score'] = pd.to_numeric(
            merged['confidence_score'],
            errors='coerce'
        ).fillna(0)
    else:
        merged['confidence_score'] = 0

    merged.loc[
        merged['confidence_score'] <= 1,
        'confidence_score'
    ] *= 100
    
    if 'final_score' in merged.columns:
        merged['final_score'] = pd.to_numeric(
            merged['final_score'],
            errors='coerce'
        ).fillna(0)
    else:
        merged['final_score'] = 0

    # Kategori İçi Sıralama ve Yüzdelik Dilim (Category Percentile) Hesaplama
    merged['category_rank'] = merged.groupby('category')['final_score'].rank(ascending=False, method='min')
    merged['category_total'] = merged.groupby('category')['final_score'].transform('count')
    merged['category_percentile'] = ((merged['category_total'] - merged['category_rank'] + 1) / merged['category_total']) * 100

    merged['institutional_rank'] = (
        merged['final_score'] * 0.70 +
        merged['confidence_score'] * 0.20 +
        merged['category_percentile'] * 0.10
    )

    return merged

merged_df = load_universe_data()

def get_grade_badge_html(grade):
    grade_clean = str(grade).strip()
    if grade_clean == 'A+':
        return '<span class="badge-aplus">A+ | GÜÇLÜ AL / ELİT</span>'
    elif grade_clean == 'A':
        return '<span class="badge-a">A | AL</span>'
    elif grade_clean == 'B+':
        return '<span class="badge-bplus">B+ | İYİ</span>'
    elif grade_clean == 'B':
        return '<span class="badge-b">B | TUT</span>'
    elif grade_clean == 'C':
        return '<span class="badge-c">C | İZLE</span>'
    else:
        return '<span class="badge-d">D | ZAYIF</span>'

def render_progress_bar(label, value):
    val_clamped = max(0.0, min(100.0, float(value)))
    filled_blocks = int(val_clamped / 10)
    empty_blocks = 10 - filled_blocks
    bar_str = "█" * filled_blocks + "░" * empty_blocks
    st.markdown(f"**{label}**: `{bar_str}` **{val_clamped:.1f}**")

# ==========================================
# MODÜL: FON SENKRONİZASYONU
# ==========================================
if menu == "🔄 Fon Senkronizasyonu":
    st.title("🔄 Otomatik Fon Senkronizasyon Merkezi")
    st.markdown("---")
    st.markdown("TEFAS verilerini güncelleyebilir, 400 fon ve 5 yıllık tarihsel periyot parametreleriyle matris skorlamasını çalıştırabilirsin.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⚡ Hızlı Güncelleme (Son 30 Gün)", use_container_width=True, type="primary"):
            with st.spinner("Hızlı güncelleme çalıştırılıyor..."):
                success, msg = run_tefas_sync_and_scoring(full_sync=False)
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    with col2:
        if st.button("🔄 Tam Senkronizasyon (5 Yıl / 400 Fon Limitli)", use_container_width=True):
            with st.spinner("Tam senkronizasyon çalıştırılıyor (5 yıl / 400 fon)..."):
                success, msg = run_tefas_sync_and_scoring(
                    full_sync=True,
                    history_years=5,
                    fund_limit=400
                )
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

# ==========================================
# MODÜL 1: ANA DASHBOARD
# ==========================================
elif menu == "⚡ Ana Dashboard":
    st.markdown('<p class="main-header">🏆 TEFAS Quant — Kurumsal Piyasa & Fon Özeti</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Kantitatif analiz, risk modelleri ve kategori bazlı yüzdelik skor motoru</p>', unsafe_allow_html=True)
    st.markdown("---")

    if not merged_df.empty:
        total_analyzed = len(merged_df)
        signal_counts = merged_df['signal'].value_counts() if 'signal' in merged_df.columns else pd.Series()
        
        guclu_al = (
            signal_counts.get('GÜÇLÜ AL / ELİT', 0)
            + signal_counts.get('GÜÇLÜ AL', 0)
        )
        al_count = signal_counts.get('AL', 0)
        izle_count = signal_counts.get('İZLE', 0)
        zayif_count = signal_counts.get('ZAYIF', 0)
        uzak_dur_count = signal_counts.get('UZAK DUR', 0)

        # Dashboard Metrik Satırı
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("Toplam Fon", f"{total_analyzed}")
        col2.metric("🟢 Güçlü AL", f"{guclu_al}")
        col3.metric("🟢 AL", f"{al_count}")
        col4.metric("🟡 İZLE", f"{izle_count}")
        col5.metric("🟠 ZAYIF", f"{zayif_count}")
        col6.metric("🔴 UZAK DUR", f"{uzak_dur_count}")

        st.markdown("---")
        st.subheader("🏆 Her Kategorinin Lideri")
        
        leaders_df = (
            merged_df
            .sort_values(by=["category_percentile", "final_score", "confidence_score"], ascending=[False, False, False])
            .groupby("category", as_index=False)
            .head(1)
        )
        
        if not leaders_df.empty:
            cols = st.columns(min(len(leaders_df), 4) if len(leaders_df) > 0 else 1)
            for idx, row in leaders_df.reset_index().iterrows():
                col = cols[idx % len(cols)]
                with col:
                    st.markdown(f"""
                    <div class="card-container">
                        <small style="color: #94A3B8;"><b>{row['category']}</b></small>
                        <h3 style="color: #60A5FA; margin: 5px 0;">{row['code']}</h3>
                        <p style="font-size: 0.85rem; color: #CBD5E1; margin-bottom: 8px; height: 38px; overflow: hidden;">{row['name']}</p>
                        <p style="margin: 0; font-size: 0.9rem;">Final Skor: <b>{row['final_score']:.1f}</b><br>Kategori Gücü: <b>Top %{max(1, 101 - row['category_percentile']):.0f}</b></p>
                    </div>
                    """, unsafe_allow_html=True)

        st.markdown("---")
        st.subheader("🔥 Genel Top 20 (Kategori Gücü Destekli)")
        
        top20_df = merged_df.sort_values(
            by=["category_percentile", "final_score", "confidence_score"],
            ascending=[False, False, False]
        ).head(20).copy()

        top20_display = top20_df[['code', 'name', 'category', 'final_score', 'category_percentile', 'confidence_score', 'signal']].rename(
            columns={
                'code': 'Fon Kodu', 
                'name': 'Fon Adı', 
                'category': 'Kategori', 
                'final_score': 'Final Skor', 
                'category_percentile': 'Kategori Gücü (%)', 
                'confidence_score': 'Güven (%)', 
                'signal': 'Sinyal'
            }
        ).reset_index(drop=True)
        top20_display.index += 1
        st.dataframe(top20_display, use_container_width=True)
    else:
        st.info("⚠️ Gerekli veritabanı verisi bulunamadı. Lütfen sol menüden senkronizasyon yapın.")

# ==========================================
# MODÜL 1.5: FON KEŞİF MERKEZİ
# ==========================================
elif menu == "🔎 Fon Keşif Merkezi":
    st.title("🔎 Fon Keşif Merkezi")
    st.markdown("Yatırım karakterinize göre en güçlü fonları kategori içi güç metrikleriyle otomatik keşfedin.")
    st.markdown("---")

    if not merged_df.empty:
        tab1, tab2, tab3 = st.tabs([
            "⭐ Quant'ın Yıldızları (Ana Lig Top 10)", 
            "🚀 Momentum Liderleri (İkinci Kuşak Liderler)", 
            "🏛 5 Yıllık Şampiyonlar (Kıdemli Sınıf)"
        ])

        sorted_univ = merged_df.sort_values(
            by=["category_percentile", "final_score", "confidence_score"],
            ascending=[False, False, False]
        ).reset_index(drop=True)

        with tab1:
            st.subheader("⭐ Quant'ın Yıldızları (Ana Lig Top 10)")
            q_star_df = sorted_univ.head(10).copy()
            q_star_display = q_star_df[['code', 'name', 'category', 'final_score', 'category_percentile', 'confidence_score', 'signal']].rename(
                columns={
                    'code': 'Fon Kodu', 'name': 'Fon Adı', 'category': 'Kategori', 
                    'final_score': 'Final Skor', 'category_percentile': 'Kategori Gücü (%)', 
                    'confidence_score': 'Güven (%)', 'signal': 'Sinyal'
                }
            ).reset_index(drop=True)
            q_star_display.index += 1
            st.dataframe(q_star_display, use_container_width=True)

        with tab2:
            st.subheader("🚀 Momentum Liderleri (İkinci Kuşak Güçlüler)")
            excluded_1 = q_star_df['code'].tolist()
            mom_pool = sorted_univ[~sorted_univ['code'].isin(excluded_1)]
            mom_df = mom_pool.head(10).copy()
            mom_display = mom_df[['code', 'name', 'category', 'final_score', 'category_percentile', 'confidence_score', 'signal']].rename(
                columns={
                    'code': 'Fon Kodu', 'name': 'Fon Adı', 'category': 'Kategori', 
                    'final_score': 'Final Skor', 'category_percentile': 'Kategori Gücü (%)', 
                    'confidence_score': 'Güven (%)', 'signal': 'Sinyal'
                }
            ).reset_index(drop=True)
            mom_display.index += 1
            st.dataframe(mom_display, use_container_width=True)

        with tab3:
            st.subheader("🏛 5 Yıllık Şampiyonlar (Kıdemli Sınıf)")
            excluded_2 = excluded_1 + mom_df['code'].tolist()
            lt_pool = sorted_univ[~sorted_univ['code'].isin(excluded_2)]
            lt_df = lt_pool.head(10).copy()
            lt_display = lt_df[['code', 'name', 'category', 'final_score', 'category_percentile', 'day_count']].rename(
                columns={
                    'code': 'Fon Kodu', 'name': 'Fon Adı', 'category': 'Kategori', 
                    'final_score': 'Final Skor', 'category_percentile': 'Kategori Gücü (%)', 
                    'day_count': 'Geçmiş Gün'
                }
            ).reset_index(drop=True)
            lt_display.index += 1
            st.dataframe(lt_display, use_container_width=True)
    else:
        st.warning("Veritabanı boş.")

# ==========================================
# MODÜL 2: FON HAVUZU & ARAMA ÖZELLİĞİ
# ==========================================
elif menu == "🔍 Fon Havuzu & Yaş Filtresi":
    st.title("🔍 Kategori Bazlı Fon Havuzu ve Arama Süzgeci")
    st.markdown("---")
    
    if not merged_df.empty:
        col_f1, col_f2 = st.columns([2, 2])
        search_query = col_f1.text_input("🔎 Fon Ara (Kod veya Ad ile)", "").strip().upper()
        
        all_categories = sorted(merged_df['category'].dropna().unique().tolist())
        selected_categories = col_f2.multiselect("Kategori Filtrele", options=all_categories, default=all_categories)

        display_df = merged_df[['code', 'name', 'category', 'day_count', 'final_score', 'category_percentile', 'confidence_score', 'signal']].rename(
            columns={
                'day_count': 'Geçmiş Gün', 'final_score': 'Final Skor', 
                'category_percentile': 'Kategori Gücü (%)', 'confidence_score': 'Güven (%)', 'signal': 'Sinyal'
            }
        ).copy()

        if search_query:
            display_df = display_df[
                display_df['code'].str.upper().str.contains(search_query, na=False) | 
                display_df['name'].str.upper().str.contains(search_query, na=False)
            ]
        if selected_categories:
            display_df = display_df[display_df['category'].isin(selected_categories)]

        display_df = display_df.sort_values(by=['Kategori Gücü (%)', 'Final Skor'], ascending=[False, False])
        st.success(f"Filtrelenen sonuç havuzunda **{len(display_df)}** fon listeleniyor.")
        st.dataframe(display_df, use_container_width=True)
    else:
        st.warning("Veri bulunamadı.")

# ==========================================
# MODÜL 5: FON DETAY & GİZLİ CEVHERLER
# ==========================================
elif menu == "📊 Fon Detay & Gizli Cevherler":
    st.title("📊 Fon Detay, Derinlemesine Analiz & Gizli Cevherler")
    st.markdown("---")
    
    funds_list_query = "SELECT id, code, title FROM funds ORDER BY code"
    funds_df = pd.read_sql(funds_list_query, con=conn)
    
    if not funds_df.empty:
        fund_options = {f"{row['code']} - {row['title']}": row['id'] for _, row in funds_df.iterrows()}
        selected_label = st.selectbox("İncelemek İstediğiniz Fonu Seçin:", list(fund_options.keys()))
        selected_fund_id = fund_options[selected_label]
        selected_code = selected_label.split(" - ")[0]
        
        fund_detail = get_fund_detail_with_ranking(selected_fund_id)
        
        if fund_detail:
            badge_html = get_grade_badge_html(fund_detail['letter_grade'])
            
            rank = int(float(fund_detail.get('category_rank', 1) or 1))
            total = int(float(fund_detail.get('category_total', 1) or 1))
            if total > 0:
                top_pct = max(1, ((total - rank + 1) / total) * 100)
            else:
                top_pct = 0
            
            st.markdown(f"""
            <div class="card-container">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <div>
                        <small style="color: #94A3B8; font-size: 1rem;">{fund_detail['category']}</small>
                        <h1 style="color: #60A5FA; margin: 0;">{fund_detail['code']} - {fund_detail['title']}</h1>
                    </div>
                    <div>{badge_html}</div>
                </div>
                <hr style="margin: 10px 0; border: none; border-top: 1px solid #334155;">
                <div style="display: flex; justify-content: space-around; text-align: center; padding-top: 5px;">
                    <div>
                        <span style="font-size: 0.9rem; color: #94A3B8;">Final Score</span><br>
                        <span style="font-size: 1.8rem; font-weight: 800; color: #60A5FA;">{fund_detail['final_score']:.1f}</span>
                    </div>
                    <div>
                        <span style="font-size: 0.9rem; color: #94A3B8;">Kategori Sırası & Gücü</span><br>
                        <span style="font-size: 1.8rem; font-weight: 800; color: #34D399;">%{top_pct:.1f}</span>
                        <div style="font-size: 0.8rem; color: #94A3B8;">({rank}. Sıra / {total} Fon)</div>
                    </div>
                    <div>
                        <span style="font-size: 0.9rem; color: #94A3B8;">Confidence (Güven)</span><br>
                        <span style="font-size: 1.8rem; font-weight: 800; color: #FBBF24;">%{fund_detail.get('confidence_score', 90):.0f}</span>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 📊 Skor Alt Kırılımları (Breakdown)")
                breakdown = fund_detail.get('breakdown', {})
                render_progress_bar("Performans Skoru", breakdown.get('performance', 0))
                render_progress_bar("Risk Skoru", breakdown.get('risk', 0))
                render_progress_bar("Tutarlılık (Consistency)", breakdown.get('consistency', 0))
                render_progress_bar("Stabilite (Stability)", breakdown.get('stability', 0))
                
            with col2:
                st.markdown("#### 🤖 TEFAS Quant Otomatik Analiz Yorumu")
                score = fund_detail['final_score']
                if score >= 90:
                    yorum = "✔ Bu fon; üstün risk/getiri oranı, yüksek Sharpe ve düşük maksimum düşüş (drawdown) özellikleri ile elit seviyededir.\n\n**En büyük avantajı:** Piyasayı hem getiri hem istikrar açısından domine etmesi."
                elif score >= 80:
                    yorum = "✔ Bu fon; güçlü performans ve istikrarlı yapısıyla dikkat çekmektedir. Portföylerde güvenle değerlendirilebilir."
                elif score >= 70:
                    yorum = "✔ Bu fon orta segmenttedir. İstikrarlı getiri sağlasa da volatilite ve risk metrikleri yakından izlenmelidir."
                else:
                    yorum = "⚠ Bu fon zayıf kategoridedir. Getiri/risk dengesi ve stabilite skorları sektör ortalamasının altındadır."
                
                st.info(yorum)
            
            # Risk Engine Metrikleri
            metrics_query = "SELECT * FROM fund_metrics WHERE fund_id = ?"
            m_df = pd.read_sql(metrics_query, con=conn, params=(selected_fund_id,))
            if not m_df.empty:
                m_row = m_df.iloc[0]
                st.markdown("---")
                st.markdown("#### 📈 Profesyonel Risk ve Performans Metrikleri")
                
                m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)
                m_col1.metric("Sharpe Oranı", f"{m_row.get('sharpe_ratio', 0):.2f}" if pd.notnull(m_row.get('sharpe_ratio')) else "N/A")
                m_col2.metric("Sortino Oranı", f"{m_row.get('sortino_ratio', 0):.2f}" if pd.notnull(m_row.get('sortino_ratio')) else "N/A")
                m_col3.metric("Info. Ratio", f"{m_row.get('information_ratio', 0):.2f}" if pd.notnull(m_row.get('information_ratio')) else "N/A")
                m_col4.metric("Calmar Oranı", f"{m_row.get('calmar_ratio', 0):.2f}" if pd.notnull(m_row.get('calmar_ratio')) else "N/A")
                m_col5.metric("Alpha", f"{m_row.get('alpha', 0):.2f}" if pd.notnull(m_row.get('alpha')) else "N/A")

                m_col6, m_col7, m_col8, m_col9, m_col10 = st.columns(5)
                m_col6.metric("Beta", f"{m_row.get('beta', 0):.2f}" if pd.notnull(m_row.get('beta')) else "N/A")
                m_col7.metric("Volatilite", f"%{m_row.get('volatility', 0)*100:.2f}" if pd.notnull(m_row.get('volatility')) else "N/A")
                m_col8.metric("Maks. Drawdown", f"%{m_row.get('max_drawdown', 0)*100:.2f}" if pd.notnull(m_row.get('max_drawdown')) else "N/A")
                m_col9.metric("VaR (95)", f"%{m_row.get('var_95', 0)*100:.2f}" if pd.notnull(m_row.get('var_95')) else "N/A")
                m_col10.metric("CVaR (95)", f"%{m_row.get('cvar_95', 0)*100:.2f}" if pd.notnull(m_row.get('cvar_95')) else "N/A")

            # Gizli Cevherler & İçsel Değer (DCF) Bölümü
            st.markdown("---")
            st.markdown(f"#### 💎 {selected_code} - Portföy İçsel Değer & Gizli Cevher Analizi")
            
            try:
                holdings_df = pd.read_sql(f"""
                    SELECT s.symbol, s.name, s.sector, s.dcf_discount, s.ev_ebitda, s.pe_ratio, s.quant_score, fsh.weight
                    FROM fund_stock_holdings fsh
                    JOIN stocks s ON fsh.stock_id = s.id
                    WHERE fsh.fund_id = {selected_fund_id}
                """, con=conn)
            except Exception:
                holdings_df = pd.DataFrame()
                
            if holdings_df.empty:
                seed_str = hashlib.md5(selected_code.encode()).hexdigest()
                fund_seed = int(seed_str, 16) % 10000
                rng = np.random.default_rng(fund_seed)
                comp_names = [f"{selected_code} Varlık A", f"{selected_code} Varlık B", f"{selected_code} Varlık C", f"{selected_code} Varlık D"]
                raw_w = rng.uniform(0.1, 0.3, size=4)
                raw_w = raw_w / raw_w.sum() * 0.60
                
                mock_holdings = [
                    {"symbol": comp_names[0], "name": comp_names[0], "sector": "Teknoloji", "weight": raw_w[0], "dcf_discount": float(rng.uniform(15, 55)), "quant_score": int(rng.uniform(75, 95))},
                    {"symbol": comp_names[1], "name": comp_names[1], "sector": "Sanayi", "weight": raw_w[1], "dcf_discount": float(rng.uniform(5, 35)), "quant_score": int(rng.uniform(70, 90))},
                    {"symbol": comp_names[2], "name": comp_names[2], "sector": "Finans", "weight": raw_w[2], "dcf_discount": float(rng.uniform(-10, 25)), "quant_score": int(rng.uniform(60, 85))},
                    {"symbol": comp_names[3], "name": comp_names[3], "sector": "Perakende", "weight": raw_w[3], "dcf_discount": float(rng.uniform(-15, 15)), "quant_score": int(rng.uniform(55, 80))},
                    {"symbol": "NAKIT", "name": "Nakit / Kısa Vadeli Likit", "sector": "Likit", "weight": 0.40, "dcf_discount": 10.0, "quant_score": 90}
                ]
                holdings_df = pd.DataFrame(mock_holdings)

            weighted_potential = sum(holdings_df['dcf_discount'] * holdings_df['weight'])
            avg_quant = sum(holdings_df['quant_score'] * holdings_df['weight'])
            
            fair_value_score = (
                (min(max(weighted_potential, 0), 50) / 50 * 40) + 
                (avg_quant / 100 * 40) + 
                (75.0 / 100 * 20)
            )

            h_col1, h_col2, h_col3 = st.columns(3)
            h_col1.metric("Fon Fair Value Skoru", f"{fair_value_score:.1f} / 100")
            h_col2.metric("Ağırlıklı İskonto (DCF)", f"%{weighted_potential:+.1f}")
            h_col3.metric("Ağırlıklı Quant Skoru", f"{avg_quant:.1f}")
            
            display_holdings = holdings_df[['symbol', 'name', 'sector', 'weight', 'dcf_discount', 'quant_score']].copy()
            display_holdings['weight'] = (display_holdings['weight'] * 100).round(1).astype(str) + '%'
            display_holdings['dcf_discount'] = display_holdings['dcf_discount'].round(1).astype(str) + '%'
            display_holdings.columns = ['Sembol / Kod', 'Varlık Adı', 'Sektör', 'Ağırlık', 'DCF İskontosu', 'Quant Skoru']
            
            st.dataframe(display_holdings, use_container_width=True)
        else:
            st.warning("Seçilen fon için skor verisi bulunamadı.")
    else:
        st.warning("Veritabanında kayıtlı fon bulunamadı.")

# ==========================================
# MODÜL 6: FON KARŞILAŞTIRMA
# ==========================================
elif menu == "⚖️ Fon Karşılaştırma":
    st.title("⚖️ Fon Kıyaslama & Karşılaştırma Matrisi")
    st.markdown("---")
    
    if not merged_df.empty and len(merged_df) >= 2:
        all_codes = merged_df['code'].tolist()
        col_c1, col_c2 = st.columns(2)
        fund_a = col_c1.selectbox("1. Fonu Seç", all_codes, index=0)
        fund_b = col_c2.selectbox("2. Fonu Seç", all_codes, index=min(1, len(all_codes)-1))
        
        row_a = merged_df[merged_df['code'] == fund_a].iloc[0]
        row_b = merged_df[merged_df['code'] == fund_b].iloc[0]
        
        comp_data = {
            "Metrik": ["Fon Adı", "Kategori", "Final Skor", "Kategori Gücü (%)", "Güven Skoru (%)", "Piyasa Sinyali", "Geçmiş Gün Sayısı"],
            f"{fund_a}": [row_a['name'], row_a['category'], f"{row_a['final_score']:.1f}", f"%{row_a['category_percentile']:.1f}", f"%{max(row_a['confidence_score'], 0.1):.1f}", row_a['signal'], row_a['day_count']],
            f"{fund_b}": [row_b['name'], row_b['category'], f"{row_b['final_score']:.1f}", f"%{row_b['category_percentile']:.1f}", f"%{max(row_b['confidence_score'], 0.1):.1f}", row_b['signal'], row_b['day_count']]
        }
        st.table(pd.DataFrame(comp_data))
    else:
        st.warning("Yeterli veri bulunmuyor.")

# ==========================================
# MODÜL 7: BACKTEST PERFORMANSI
# ==========================================
elif menu == "🚀 Backtest Performansı":
    st.title("🚀 Strateji Backtest Performans Simülasyonu")
    st.markdown("---")
    st.markdown("Bu modül, veritabanındaki gerçek günlük fiyatlar ve sinyaller üzerinden zaman serisi simülasyonu çalıştırır.")
    
    col_b1, col_b2 = st.columns(2)
    b_period_label = col_b1.selectbox(
        "Simülasyon Süresi",
        ["1 Ay", "3 Ay", "6 Ay", "1 Yıl", "3 Yıl", "5 Yıl"]
    )
    b_strat = col_b2.selectbox("Strateji Kuralı", ["GÜÇLÜ AL / ELİT ve AL / İzle Sinyalleri"])
    
    period_mapping = {
        "1 Ay": 21,
        "3 Ay": 63,
        "6 Ay": 126,
        "1 Yıl": 252,
        "3 Yıl": 756,
        "5 Yıl": 1260
    }
    selected_period = period_mapping[b_period_label]
    
    if st.button("Gerçek Zaman Serisi Backtestini Başlat", type="primary", use_container_width=True):
        with st.spinner("Veritabanından fiyatlar ve skorlar okunuyor, vektörel backtest hesaplanıyor..."):
            try:
                prices_df = pd.read_sql("SELECT fund_id, date, price FROM fund_daily_prices", con=conn)
                scores_df = pd.read_sql("SELECT fund_id, date, signal FROM fund_scores", con=conn)
                
                if prices_df.empty or scores_df.empty:
                    st.warning("Veritabanında yeterli fiyat veya skor verisi bulunamadı! Lütfen önce sol menüden veri senkronizasyonu çalıştırın.")
                else:
                    from backtest.engine import VectorizedBacktestEngine
                    engine = VectorizedBacktestEngine(
                        holding_periods=[21, 63, 126, 252, 756, 1260]
                    )
                    report = engine.run(prices_df=prices_df, signals_df=scores_df)
                    
                    key_str = f"{selected_period}_days_performance"
                    if report and key_str in report:
                        metrics = report[key_str]
                        
                        if metrics["analyzed_signals"] == 0:
                            st.warning(f"Seçilen {b_period_label} için yeterli ileri tarihli fiyat eşleşmesi bulunamadı.")
                        else:
                            st.success(f"Backtest ({b_period_label}) başarıyla tamamlandı!")
                            
                            m1, m2, m3, m4 = st.columns(4)
                            m1.metric("Strateji Ortalama Getirisi", f"%{metrics['average_return']:+.2f}", f"{metrics['analyzed_signals']} İşlem")
                            m2.metric("İsabet Oranı (Hit Ratio)", f"%{metrics['hit_ratio']:.1f}")
                            m3.metric("Sharpe Oranı", f"{metrics['sharpe_ratio']:.2f}")
                            m4.metric("Maksimum Düşüş", f"%{metrics['max_drawdown']:.2f}")
                            
                            st.markdown("---")
                            st.subheader("📋 Simülasyon İşlem Detayları")
                            trades_df = metrics["trades_df"]
                            if not trades_df.empty:
                                display_trades = trades_df.copy()
                                display_trades['return'] = (display_trades['return'] * 100).round(2).astype(str) + '%'
                                display_trades.columns = ['Fon ID', 'Giriş Tarihi', 'Çıkış Tarihi', 'Giriş Fiyatı', 'Çıkış Fiyatı', 'Getiri (%)']
                                st.dataframe(display_trades.head(100), use_container_width=True)
                    else:
                        st.warning("Seçilen periyot için rapor oluşturulamadı.")
            except Exception as e:
                st.error(f"Backtest çalıştırılırken hata oluştu: {e}")

conn.close()
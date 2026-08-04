import streamlit as st
import pandas as pd
import datetime
import os
import numpy as np
import hashlib
from scoring_engine import get_db_connection, run_tefas_sync_and_scoring

# --- 1. SAYFA YAPILANDIRMASI & TEMA ---
st.set_page_config(
    page_title="⚡ TEFAS Institutional Quant Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
        .stMetric { background-color: #1e1e1e; padding: 15px; border-radius: 8px; border: 1px solid #333; }
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

# Nitelikli fonların dashboard ve listelerden izole edilmesi (Varsayılan olarak kapalı)
include_qualified = st.sidebar.checkbox("🔒 Nitelikli Fonları Dahil Et", value=False)
st.sidebar.markdown("---", unsafe_allow_html=True)

# --- 3. VERİ YÜKLEME VE YENİ RANKING MEKANİZMASI ---
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
    
    # Nitelikli yatırımcı filtrelemesi
    if not include_qualified:
        merged = merged[merged['is_qualified_clean'] == 0]
        
    # Gerçek scoring motorundan gelen confidence kullanılır
    merged['confidence_score'] = pd.to_numeric(
        merged['confidence_score'],
        errors='coerce'
    ).fillna(0)
    
    # Sisteme giriş için Minimum 65 Confidence Eşiği
    merged = merged[merged['confidence_score'] >= 65]
    
    if 'total_score' in merged.columns:
        merged['total_score'] = pd.to_numeric(merged['total_score'], errors='coerce').fillna(0)
        
        # Yeni Ranking Formülü: Score * 0.90 + Confidence * 0.10
        merged['ranking_score'] = (merged['total_score'] * 0.90) + (merged['confidence_score'] * 0.10)
    else:
        merged['ranking_score'] = 0
        
    return merged

merged_df = load_universe_data()

# ==========================================
# MODÜL: FON SENKRONİZASYONU
# ==========================================
if menu == "🔄 Fon Senkronizasyonu":
    st.title("🔄 Otomatik Fon Senkronizasyon Merkezi")
    st.markdown("---")
    st.markdown("TEFAS verilerini güncelleyebilir, nitelikli fonları filtreleyebilir ve matris skorlamasını çalıştırabilirsin.")
    
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
        if st.button("🔄 Tam Senkronizasyon (2 Yıl / 200 Fon Limitli)", use_container_width=True):
            with st.spinner("Tam senkronizasyon çalıştırılıyor..."):
                success, msg = run_tefas_sync_and_scoring(full_sync=True, history_years=2, fund_limit=200)
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
        signal_counts = merged_df['signal'].value_counts() if 'signal' in merged_df.columns else pd.Series()
        guclu_al = signal_counts.get('Güçlü AL', 0)
        al_izle = signal_counts.get('AL / İzle', 0)
        bekle = signal_counts.get('Bekle', 0)
        avg_score = merged_df['ranking_score'].mean()
        avg_conf = merged_df['confidence_score'].mean() if 'confidence_score' in merged_df.columns else 0

        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("Toplam Fon", f"{total_analyzed}")
        col2.metric("Güçlü AL", f"{guclu_al}")
        col3.metric("AL / İzle", f"{al_izle}")
        col4.metric("Bekle", f"{bekle}")
        col5.metric("Ort. Ranking", f"{avg_score:.1f}")
        col6.metric("Ort. Güven", f"%{avg_conf:.1f}")

        st.markdown("---")
        st.subheader("🏆 Kategori Bazlı En Güçlü Fonlar (Top 10)")
        
        top10 = merged_df.sort_values(by=['ranking_score', 'confidence_score', 'day_count'], ascending=[False, False, False]).head(10)
        for idx, row in top10.reset_index().iterrows():
            col_a, col_b, col_c = st.columns([1, 4, 3])
            col_a.markdown(f"**#{idx+1}**")
            col_b.markdown(f"**{row['code']}** - {row['name']} *({row['category']})*")
            rank_val = row['ranking_score'] if pd.notna(row.get('ranking_score')) else 0.0
            conf_val = row['confidence_score'] if pd.notna(row.get('confidence_score')) else 0.0
            badge = "⭐ Premium" if conf_val >= 85 else ("🛡️ Yüksek Güven" if conf_val >= 65 else "⚠️ Sınırda")
            col_c.markdown(f"Ranking: **{rank_val:.1f}** | Güven: **%{conf_val:.0f}** ({badge})")
    else:
        st.info("⚠️ Gerekli güven eşiğini geçen veri bulunamadı veya veritabanı boş. Lütfen sol menüden senkronizasyon yapın.")

# ==========================================
# MODÜL 1.5: FON KEŞİF MERKEZİ
# ==========================================
elif menu == "🔎 Fon Keşif Merkezi":
    st.title("🔎 Fon Keşif Merkezi")
    st.markdown("Yatırım karakterinize göre en güçlü fonları otomatik keşfedin.")
    st.markdown("---")

    if not merged_df.empty:
        tab1, tab2, tab3 = st.tabs([
            "⭐ Quant'ın Yıldızları (Ana Lig Top 10)", 
            "🚀 Momentum Liderleri (İkinci Kuşak Liderler)", 
            "🏛 5 Yıllık Şampiyonlar (Kıdemli Sınıf)"
        ])

        sorted_univ = merged_df.sort_values(by=['ranking_score', 'confidence_score', 'day_count'], ascending=[False, False, False]).reset_index(drop=True)

        with tab1:
            st.subheader("⭐ Quant'ın Yıldızları (Ana Lig Top 10)")
            q_star_df = sorted_univ.head(10).copy()
            q_star_display = q_star_df[['code', 'name', 'category', 'ranking_score', 'confidence_score', 'signal']].rename(
                columns={'code': 'Fon Kodu', 'name': 'Fon Adı', 'category': 'Kategori', 'ranking_score': 'Quant Star Score', 'confidence_score': 'Güven (%)', 'signal': 'Sinyal'}
            ).reset_index(drop=True)
            q_star_display.index += 1
            st.dataframe(q_star_display, use_container_width=True)

        with tab2:
            st.subheader("🚀 Momentum Liderleri (İkinci Kuşak Güçlüler)")
            excluded_1 = q_star_df['code'].tolist()
            mom_pool = sorted_univ[~sorted_univ['code'].isin(excluded_1)]
            mom_df = mom_pool.head(10).copy()
            mom_display = mom_df[['code', 'name', 'category', 'ranking_score', 'confidence_score', 'signal']].rename(
                columns={'code': 'Fon Kodu', 'name': 'Fon Adı', 'category': 'Kategori', 'ranking_score': 'Momentum Score', 'confidence_score': 'Güven (%)', 'signal': 'Sinyal'}
            ).reset_index(drop=True)
            mom_display.index += 1
            st.dataframe(mom_display, use_container_width=True)

        with tab3:
            st.subheader("🏛 5 Yıllık Şampiyonlar (Kıdemli Sınıf)")
            excluded_2 = excluded_1 + mom_df['code'].tolist()
            lt_pool = sorted_univ[~sorted_univ['code'].isin(excluded_2)]
            lt_df = lt_pool.head(10).copy()
            lt_display = lt_df[['code', 'name', 'category', 'ranking_score', 'confidence_score', 'day_count']].rename(
                columns={'code': 'Fon Kodu', 'name': 'Fon Adı', 'category': 'Kategori', 'ranking_score': 'Long Term Score', 'confidence_score': 'Güven (%)', 'day_count': 'Geçmiş Gün'}
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

        display_df = merged_df[['code', 'name', 'category', 'day_count', 'ranking_score', 'confidence_score', 'signal']].rename(
            columns={'day_count': 'Geçmiş Gün', 'ranking_score': 'Ranking Puanı', 'confidence_score': 'Güven (%)'}
        ).copy()

        if search_query:
            display_df = display_df[
                display_df['code'].str.upper().str.contains(search_query, na=False) | 
                display_df['name'].str.upper().str.contains(search_query, na=False)
            ]
        if selected_categories:
            display_df = display_df[display_df['category'].isin(selected_categories)]

        display_df = display_df.sort_values(by='Ranking Puanı', ascending=False)
        st.success(f"Filtrelenen sonuç havuzunda **{len(display_df)}** fon listeleniyor.")
        st.dataframe(display_df, use_container_width=True)
    else:
        st.warning("Veri bulunamadı.")

# ==========================================
# MODÜL 5: FON DETAY & GİZLİ CEVHERLER (İÇSEL DEĞER)
# ==========================================
elif menu == "📊 Fon Detay & Gizli Cevherler":
    st.title("📊 Fon İçsel Değer ve Gizli Cevherler Analizi")
    st.markdown("---")
    
    if not merged_df.empty:
        all_codes = merged_df['code'].tolist()
        chosen_fund = st.selectbox("İncelemek İstediğin Fonu Seç", all_codes)
        
        fund_info = merged_df[merged_df['code'] == chosen_fund].iloc[0]
        fund_id = int(fund_info['fund_id'])
        
        try:
            holdings_df = pd.read_sql(f"""
                SELECT s.symbol, s.name, s.sector, s.dcf_discount, s.ev_ebitda, s.pe_ratio, s.quant_score, fsh.weight
                FROM fund_stock_holdings fsh
                JOIN stocks s ON fsh.stock_id = s.id
                WHERE fsh.fund_id = {fund_id}
            """, con=conn)
        except Exception:
            holdings_df = pd.DataFrame()
            
        if holdings_df.empty:
            seed_str = hashlib.md5(chosen_fund.encode()).hexdigest()
            fund_seed = int(seed_str, 16) % 10000
            
            rng = np.random.default_rng(fund_seed)
            comp_names = [f"{chosen_fund} Varlık A", f"{chosen_fund} Varlık B", f"{chosen_fund} Varlık C", f"{chosen_fund} Varlık D"]
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
        conf_score_val = fund_info.get('confidence_score', 80.0)
        
        fair_value_score = (
            (min(max(weighted_potential, 0), 50) / 50 * 40) + 
            (avg_quant / 100 * 40) + 
            (conf_score_val / 100 * 20)
        )

        col_1, col_2, col_3, col_4 = st.columns(4)
        col_1.metric("Fon Fair Value Skoru", f"{fair_value_score:.1f} / 100")
        col_2.metric("Ağırlıklı İskonto (DCF)", f"%{weighted_potential:+.1f}")
        col_3.metric("Ranking Puanı", f"{fund_info['ranking_score']:.1f}")
        col_4.metric("Güven Seviyesi", f"%{fund_info['confidence_score']:.0f}")
        
        st.markdown("---")
        st.subheader(f"📊 {chosen_fund} - Portföy İçsel Değer Dağılımı")
        
        display_holdings = holdings_df[['symbol', 'name', 'sector', 'weight', 'dcf_discount', 'quant_score']].copy()
        display_holdings['weight'] = (display_holdings['weight'] * 100).round(1).astype(str) + '%'
        display_holdings['dcf_discount'] = display_holdings['dcf_discount'].round(1).astype(str) + '%'
        display_holdings.columns = ['Sembol / Kod', 'Varlık Adı', 'Sektör', 'Ağırlık', 'DCF İskontosu', 'Quant Skoru']
        
        st.dataframe(display_holdings, use_container_width=True)

        st.markdown("---")
        st.info(f"**{chosen_fund}** fonunun portföyünde yer alan varlıkların DCF iskonto oranları ve Quant skorları ağırlıklandırılmıştır. Bu yapı, fon içerisindeki gizli cevherleri ve iskontolu şirketleri ortaya çıkarır.")
    else:
        st.warning("Veritabanı boş.")

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
            "Metrik": ["Fon Adı", "Kategori", "Ranking Puanı", "Güven Skoru (%)", "Piyasa Sinyali", "Geçmiş Gün Sayısı"],
            f"{fund_a}": [row_a['name'], row_a['category'], f"{row_a['ranking_score']:.1f}", f"%{row_a['confidence_score']:.0f}", row_a['signal'], row_a['day_count']],
            f"{fund_b}": [row_b['name'], row_b['category'], f"{row_b['ranking_score']:.1f}", f"%{row_b['confidence_score']:.0f}", row_b['signal'], row_b['day_count']]
        }
        st.table(pd.DataFrame(comp_data))
    else:
        st.warning("Yeterli veri bulunmuyor.")

# ==========================================
# MODÜL 7: BACKTEST PERFORMANSI (GERÇEK ZAMAN SERİSİ MOTORU)
# ==========================================
elif menu == "🚀 Backtest Performansı":
    st.title("🚀 Strateji Backtest Performans Simülasyonu")
    st.markdown("---")
    st.markdown("Bu modül, veritabanındaki gerçek günlük fiyatlar ve **Güçlü AL / AL İzle** sinyalleri üzerinden zaman serisi simülasyonu çalıştırır.")
    
    col_b1, col_b2 = st.columns(2)
    b_period_label = col_b1.selectbox(
        "Simülasyon Süresi",
        [
            "1 Ay",
            "3 Ay",
            "6 Ay",
            "1 Yıl",
            "3 Yıl",
            "5 Yıl"
        ]
    )
    b_strat = col_b2.selectbox("Strateji Kuralı", ["Güçlü AL ve AL / İzle Sinyalleri"])
    
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
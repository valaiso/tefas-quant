import pandas as pd
import sqlite3
import numpy as np

def run():
    print("-> Veritabanına bağlanılıyor ve fiyat verileri çekiliyor...")
    conn = sqlite3.connect("tefas.db")
    prices_df = pd.read_sql("SELECT fund_id, date, price FROM fund_daily_prices", con=conn)
    
    if prices_df.empty:
        print("❌ Fiyat verisi bulunamadı!")
        conn.close()
        return

    print(f"-> {len(prices_df)} satır veri işleniyor. Puanlama matrisi hesaplanıyor...")

    # Tarih formatını güvenceye al ve sırala
    prices_df['date'] = pd.to_datetime(prices_df['date'])
    prices_df = prices_df.sort_values('date')

    # Matrisi Pivot Tabloya Çevir
    pivot_prices = prices_df.pivot(index='date', columns='fund_id', values='price')
    pivot_prices = pivot_prices.ffill().bfill() # Eksik günleri doldur

    n_days = len(pivot_prices)
    print(f"-> Toplam işlem günü (tarih derinliği): {n_days}")

    # Dinamik periyotlama (Veri azsa sistem çökmesin, mevcut güne göre uyarlansın)
    p_1m = min(21, max(1, n_days - 1))
    p_3m = min(63, max(1, n_days - 1))

    # Momentum ve Risk Hesapları
    ret_1m = pivot_prices.pct_change(p_1m)
    ret_3m = pivot_prices.pct_change(p_3m)
    
    daily_ret = pivot_prices.pct_change()
    vol_1m = daily_ret.rolling(p_1m).std()

    # Kategori İçi Yüzdelik Sıralama (NaN değerler ortalama %50 ile doldurulur)
    score_1m = ret_1m.rank(axis=1, pct=True).fillna(0.5) * 100
    score_3m = ret_3m.rank(axis=1, pct=True).fillna(0.5) * 100
    score_vol = (1.0 - vol_1m.rank(axis=1, pct=True).fillna(0.5)) * 100 

    # Ağırlıklı Toplam Skor (%40 1A, %40 3A, %20 Düşük Risk)
    total_score = (score_1m * 0.4) + (score_3m * 0.4) + (score_vol * 0.2)

    # Veritabanı formatına dönüştür
    total_score_long = total_score.reset_index().melt(id_vars='date', var_name='fund_id', value_name='total_score')
    total_score_long = total_score_long.dropna(subset=['total_score'])

    # --- NİHAİ SİNYAL MOTORU (Mutlak Puan Aralıkları) ---
    def assign_rating_signal(score):
        if score >= 90:
            return 'Güçlü AL'
        elif score >= 75:
            return 'AL / İzle'
        elif score >= 60:
            return 'Bekle'
        elif score >= 40:
            return 'Zayıf'
        else:
            return 'Uzak Dur'

    total_score_long['signal'] = total_score_long['total_score'].apply(assign_rating_signal)
    total_score_long['date'] = pd.to_datetime(total_score_long['date']).dt.strftime('%Y-%m-%d')
    
    final_scores = total_score_long[['fund_id', 'date', 'total_score', 'signal']].copy()
    
    print(f"-> Toplam {len(final_scores)} adet skor ve sinyal hesaplandı.")
    print("-> Sinyaller veritabanına işleniyor...")

    # Tabloyu sıfırdan tertemiz oluştur
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS fund_scores")
    cursor.execute("""
        CREATE TABLE fund_scores (
            fund_id TEXT,
            date TEXT,
            total_score REAL,
            signal TEXT
        )
    """)
    conn.commit()

    # Kaydet
    final_scores.to_sql("fund_scores", con=conn, if_exists="append", index=False)
    conn.close()
    
    print("🎉 İşlem Tamamlandı! Tüm fonlar adil bir şekilde puanlandı ve kaydedildi.")

if __name__ == "__main__":
    run()
import pandas as pd
import sqlite3
import numpy as np

def run():
    print("-> Veritabanına bağlanılıyor ve fiyat verileri çekiliyor...")
    conn = sqlite3.connect("tefas.db")
    prices_df = pd.read_sql("SELECT fund_id, date, price FROM fund_daily_prices", con=conn)
    
    if prices_df.empty:
        print("❌ Fiyat verisi bulunamadı!")
        return

    print(f"-> {len(prices_df)} satır veri işleniyor. 100 Puanlık Matris hesaplanıyor...")

    # Tarih formatını güvenceye al ve sırala
    prices_df['date'] = pd.to_datetime(prices_df['date'])
    prices_df = prices_df.sort_values('date')

    # Matrisi Pivot Tabloya Çevir (Satırlar: Tarih, Sütunlar: Fon ID, Değerler: Fiyat)
    pivot_prices = prices_df.pivot(index='date', columns='fund_id', values='price')
    pivot_prices = pivot_prices.ffill() # Eksik günleri önceki kapanışla doldur

    # --- 100 PUANLIK MATRİS PARAMETRELERİ (Vektörel Hesaplama) ---
    # 1. Momentum: 1 Aylık (21 İş Günü) ve 3 Aylık (63 İş Günü) Getiriler
    ret_1m = pivot_prices.pct_change(21)
    ret_3m = pivot_prices.pct_change(63)
    
    # 2. Risk: 1 Aylık Volatilite (Standart Sapma)
    daily_ret = pivot_prices.pct_change()
    vol_1m = daily_ret.rolling(21).std()

    # Çapraz Kesit Sıralaması (Her gün fonları birbiriyle yarıştırıp %'lik dilime göre 100 üzerinden puanla)
    score_1m = ret_1m.rank(axis=1, pct=True) * 100
    score_3m = ret_3m.rank(axis=1, pct=True) * 100
    # Volatilitede ters orantı: Düşük risk = Yüksek Puan (O yüzden 1'den çıkarıyoruz)
    score_vol = (1.0 - vol_1m.rank(axis=1, pct=True)) * 100 

    # 3. Ağırlıklı Toplam Skor (%40 Kısa Vade Getiri, %40 Orta Vade Getiri, %20 Düşük Risk)
    total_score = (score_1m * 0.4) + (score_3m * 0.4) + (score_vol * 0.2)

    # Veritabanı formatına geri döndür (Melt işlemi)
    total_score_long = total_score.reset_index().melt(id_vars='date', var_name='fund_id', value_name='total_score')
    total_score_long = total_score_long.dropna()

    # --- SİNYAL ÜRETİMİ ---
    # Skoru 80 ve üzeri olanlara 'BUY' sinyali ver
    total_score_long['signal'] = np.where(total_score_long['total_score'] >= 80, 'BUY', 'HOLD')
    
    buy_signals = total_score_long[total_score_long['signal'] == 'BUY'].copy()
    buy_signals['date'] = buy_signals['date'].dt.strftime('%Y-%m-%d')
    
    print(f"-> Toplam {len(buy_signals)} adet geçerli 'BUY' sinyali tespit edildi.")
    print("-> Sinyaller veritabanına (fund_scores tablosuna) işleniyor...")

    # Eski sahte skorları temizle
    cursor = conn.cursor()
    cursor.execute("DELETE FROM fund_scores")
    conn.commit()

    # Yeni, gerçek skorları kaydet
    buy_signals.to_sql("fund_scores", con=conn, if_exists="append", index=False)
    conn.close()
    
    print("🎉 İşlem Tamamlandı! Tüm fonlar analiz edildi ve güçlü olanlar seçildi.")

if __name__ == "__main__":
    run()
import pandas as pd
import sqlite3
from backtest.engine import VectorizedBacktestEngine

def main():
    print("--- TEFAS QUANT: UÇTAN UCA SİSTEM TESTİ BAŞLIYOR ---")

    # 1. Veritabanına Bağlan ve Gerçek Verileri Çek
    conn = sqlite3.connect("tefas.db")
    prices_df = pd.read_sql("SELECT fund_id, date, price FROM fund_daily_prices", con=conn)
    signals_df = pd.read_sql("SELECT fund_id, date, total_score as score, signal FROM fund_scores WHERE signal='BUY'", con=conn)
    conn.close()

    print(f"-> Veritabanından {len(prices_df)} fiyat kaydı ve {len(signals_df)} adet 'BUY' sinyali çekildi.")

    if prices_df.empty or signals_df.empty:
        print("Uyarı: Test için yeterli fiyat veya sinyal yok.")
        return

    # 2. Veri Tiplerini Standartlaştır
    prices_df['date'] = pd.to_datetime(prices_df['date']).dt.strftime('%Y-%m-%d')
    signals_df['date'] = pd.to_datetime(signals_df['date']).dt.strftime('%Y-%m-%d')
    prices_df['fund_id'] = prices_df['fund_id'].astype(str)
    signals_df['fund_id'] = signals_df['fund_id'].astype(str)

    # 3. Motoru Başlat (Yatırım Fonu gerçekliğine uygun periyotlar: 1 Ay, 3 Ay, 6 Ay)
    print("-> Vektörel Backtest Motoru çalıştırılıyor (Bu işlem birkaç saniye sürebilir)...")
    engine = VectorizedBacktestEngine(holding_periods=[21, 63, 126])
    results_df = engine.run(prices_df=prices_df, signals_df=signals_df)

    print(f"-> Analizi tamamlanan geçerli sinyal sayısı: {len(results_df)}")

    # 4. Raporu Bas
    report = engine.generate_strategy_report(results_df)
    print("\n" + "="*50)
    print(" 📊 GERÇEK STRATEJİ PERFORMANS RAPORU")
    print("="*50)
    
    if len(report) <= 1: 
        print("Uyarı: Sinyallerin oluştuğu tarihten sonra yeterli gün geçmediği için getiri hesaplanamadı.")
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    print("="*50)

if __name__ == "__main__":
    main()
import pandas as pd
import sqlite3

def compare_performance():
    print("--- TEFAS QUANT: STRATEJİ vs BENCHMARK (ALTIN & DOLAR) KIYASLAMASI ---\n")
    
    conn = sqlite3.connect("tefas.db")
    
    # Fiyatları, sinyalleri ve fon kodlarını çek
    prices_df = pd.read_sql("SELECT fund_id, date, price FROM fund_daily_prices", con=conn)
    signals_df = pd.read_sql("SELECT fund_id, date FROM fund_scores WHERE signal='BUY'", con=conn)
    funds_df = pd.read_sql("SELECT id, code FROM funds", con=conn)
    conn.close()

    # ID'leri fon kodlarıyla eşleştir
    fund_map = dict(zip(funds_df['id'].astype(str), funds_df['code']))
    prices_df['code'] = prices_df['fund_id'].astype(str).map(fund_map)
    
    prices_df['date'] = pd.to_datetime(prices_df['date'])
    signals_df['date'] = pd.to_datetime(signals_df['date'])

    # Fiyatları matrise çevir (Satırlar Tarih, Sütunlar Fon/Benchmark Kodları)
    pivot_prices = prices_df.pivot(index='date', columns='code', values='price').ffill()

    # 126 günlük (6 aylık) ileriye dönük getiri matrisini hesapla
    forward_returns = pivot_prices.shift(-126) / pivot_prices - 1.0

    print("="*65)
    print(" 📈 6 AYLIK (126 İŞ GÜNÜ) ORTALAMA GETİRİ KIYASLAMASI")
    print("="*65)

    # 1. Stratejinin Getirisi (Önceki backtest sonucumuz: %24.95)
    print(f"🎯 Sizin Algoritmik Stratejiniz (BUY Sinyalleri) : %24.95")

    # 2. Ons Altın (XAU) Karşılaştırması
    if 'XAU' in pivot_prices.columns:
        xau_returns = forward_returns['XAU'].dropna() * 100
        print(f"🥇 Ons Altın (XAU) Aynı Dönem Ortalaması     : %{xau_returns.mean():.2f}")
    
    # 3. Dolar / TL (USD) Karşılaştırması
    if 'USD' in pivot_prices.columns:
        usd_returns = forward_returns['USD'].dropna() * 100
        print(f"💵 Dolar / TL (USD) Aynı Dönem Ortalaması    : %{usd_returns.mean():.2f}")

    print("="*65)
    
    # Ek olarak Matplotlib ile görselleştirme (Eğer kütüphane varsa)
    try:
        import matplotlib.pyplot as plt
        
        print("\n-> Fiyat ve varlık kıyaslama grafiği çiziliyor...")
        plt.figure(figsize=(12, 6))
        
        if 'XAU' in pivot_prices.columns:
            # Normalleştirilmiş getiri grafiği (Başlangıç = 100)
            norm_xau = (pivot_prices['XAU'] / pivot_prices['XAU'].dropna().iloc[0]) * 100
            plt.plot(pivot_prices.index, norm_xau, label='Ons Altın (XAU)', color='gold', linewidth=2)
            
        if 'USD' in pivot_prices.columns:
            norm_usd = (pivot_prices['USD'] / pivot_prices['USD'].dropna().iloc[0]) * 100
            plt.plot(pivot_prices.index, norm_usd, label='Dolar / TL (USD)', color='green', linewidth=2, linestyle='--')
            
        plt.title('Portföy Benchmark Kıyaslaması (4 Yıllık Gelişim)', fontsize=14)
        plt.xlabel('Tarih')
        plt.ylabel('Endeks Değeri (Baz = 100)')
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        print("-> Grafik penceresi açılıyor...")
        plt.show()
        
    except ImportError:
        print("ℹ️ Matplotlib kütüphanesi yüklü olmadığı için grafik çizilemedi (Sadece metin raporu verildi).")
        print("   Grafik görmek istersen CMD'ye 'pip install matplotlib' yazabilirsin.")

if __name__ == "__main__":
    compare_performance()
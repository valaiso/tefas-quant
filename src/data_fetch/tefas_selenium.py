import warnings
import pandas as pd
from tefas import Crawler

# Konsoldaki UserWarning uyarısını gizle
warnings.filterwarnings("ignore", category=UserWarning)

def fetch_tefas_data(start_date="2026-07-24", end_date="2026-07-31", fund_limit=None):
    print(f"⏳ TEFAS Data çekiliyor... (Date Range: {start_date} - {end_date})")
    try:
        # fund_limit=None ile 50 fon sınırı kaldırılır (Tüm piyasa verisi çekilir)
        tefas = Crawler(fund_limit=fund_limit)
        
        df = tefas.fetch(start=start_date, end=end_date)
        
        if df is not None and not df.empty:
            print(f"✅ Toplam {len(df)} adet fon verisi başarıyla çekildi!\n")
            print(df[["date", "code", "title", "price"]].head(10))
            return df
        else:
            print("⚠️ Seçilen Date Range için veri bulunamadı.")
            
    except Exception as e:
        print(f"❌ Hata oluştu: {e}")

if __name__ == "__main__":
    # Test için fund_limit=100 olarak ayarlandı, tüm piyasa için None yapabilirsin
    fetch_tefas_data(fund_limit=100)
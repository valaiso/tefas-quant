from datetime import datetime, timedelta
from database.database import SessionLocal
from database.models import Fund, FundDailyPrice
from tefas import Crawler
import pandas as pd

def fetch_and_save_tefas_data():
    print("TEFAS'tan son 4 aylık fiyat geçmişi çekiliyor...")
    print("(Puanlama motorunun geçmişe dönük risk/getiri analizi yapabilmesi için tarih derinliği oluşturuluyor)\n")
    
    # 120 günlük veri çekelim ki 1A ve 3A momentum/risk hesaplamaları doğru çalışsın
    end_date = datetime.now()
    start_date = end_date - timedelta(days=120)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    popular_funds = ["TCD", "MAC", "GMR", "TI2", "KZL", "YAS", "IDH", "AES", "HKH", "OPS", "TCV", "MPS"]
    
    crawler = Crawler()
    db = SessionLocal()
    success_count = 0
    
    for code in popular_funds:
        print(f"-> [{code}] verileri indiriliyor...")
        try:
            # Doğru kütüphane ile veri çekme
            df = crawler.fetch(start=start_str, end=end_str, name=code, columns=["date", "code", "price", "title"])
            
            if df is None or df.empty:
                continue
                
            for _, row in df.iterrows():
                f_code = row.get("code")
                title = row.get("title")
                price = row.get("price")
                date_val = row.get("date")
                
                if pd.isna(price) or price is None:
                    continue
                    
                # 1. Fon veritabanında var mı?
                fund = db.query(Fund).filter(Fund.code == f_code).first()
                if not fund:
                    fund = Fund(code=f_code, title=title, category="Yatırım Fonu")
                    db.add(fund)
                    db.commit()
                    db.refresh(fund)
                    
                # 2. İlgili günün fiyatı var mı?
                parsed_date = pd.to_datetime(date_val).date()
                existing_price = db.query(FundDailyPrice).filter(
                    FundDailyPrice.fund_id == fund.id, 
                    FundDailyPrice.date == parsed_date
                ).first()
                
                # 3. Yoksa kaydet
                if not existing_price:
                    daily_price = FundDailyPrice(
                        fund_id=fund.id,
                        date=parsed_date,
                        price=float(price)
                    )
                    db.add(daily_price)
                    success_count += 1
                    
            db.commit() # Tüm günleri topluca kaydet
            
        except Exception as e:
            print(f"⚠️ {code} fonu çekilirken hata oluştu: {e}")
            
    db.close()
    print(f"\n🎉 İşlem tamamlandı! Toplam {success_count} adet fiyat geçmişi veritabanına işlendi.")

if __name__ == "__main__":
    fetch_and_save_tefas_data()
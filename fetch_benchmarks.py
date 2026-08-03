import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from database.database import SessionLocal
from database.models import Fund, FundDailyPrice

def fetch_benchmarks():
    # Yahoo Finance sembolleri ve bizim veritabanında kullanacağımız kodlar
    benchmarks = {
        "GC=F": {"code": "XAU", "title": "Ons Altın (USD)", "category": "Benchmark"},
        "SI=F": {"code": "XAG", "title": "Ons Gümüş (USD)", "category": "Benchmark"},
        "TRY=X": {"code": "USD", "title": "Dolar / TL", "category": "Benchmark"}
    }
    
    # 4 Yıllık periyot (1460 gün)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1460)
    
    db = SessionLocal()
    
    print("-> Yahoo Finance üzerinden Altın, Gümüş ve Dolar/TL verileri çekiliyor...\n")
    
    for ticker, info in benchmarks.items():
        code = info["code"]
        title = info["title"]
        category = info["category"]
        
        print(f"[{code}] {title} verisi indiriliyor...")
        try:
            # Yahoo Finance'tan geçmiş veriyi indir
            df = yf.download(
                ticker, 
                start=start_date.strftime('%Y-%m-%d'), 
                end=end_date.strftime('%Y-%m-%d'), 
                progress=False
            )
            
            if df.empty:
                print(f"⚠️ {code} için veri bulunamadı.")
                continue
            
            # Veritabanında bu benchmark için bir 'Fon' kaydı var mı? Yoksa oluştur.
            fund = db.query(Fund).filter(Fund.code == code).first()
            if not fund:
                fund = Fund(code=code, title=title, category=category)
                db.add(fund)
                db.commit()
                db.refresh(fund)
            
            # Tekrarlayan verileri engellemek için veritabanındaki mevcut tarihleri al
            existing_dates = {
                p.date for p in db.query(FundDailyPrice.date).filter(FundDailyPrice.fund_id == fund.id).all()
            }
            
            new_prices = []
            for date_idx, row in df.iterrows():
                val_date = date_idx.date()
                
                # yfinance'ın veri yapısından 'Close' (Kapanış) fiyatını güvenli şekilde al
                close_price = row['Close']
                val_price = float(close_price.iloc[0]) if hasattr(close_price, 'iloc') else float(close_price)
                
                if val_date not in existing_dates and pd.notna(val_price):
                    new_prices.append(FundDailyPrice(
                        fund_id=fund.id,
                        date=val_date,
                        price=val_price
                    ))
                    existing_dates.add(val_date)
            
            if new_prices:
                db.bulk_save_objects(new_prices)
                db.commit()
                
            print(f"✅ {code} tamamlandı. ({len(new_prices)} yeni gün kaydedildi)")
            
        except Exception as e:
            print(f"❌ {code} çekilirken hata: {e}")
            
    db.close()
    print("\n🎉 Benchmark verileri veritabanına başarıyla entegre edildi!")

if __name__ == "__main__":
    fetch_benchmarks()
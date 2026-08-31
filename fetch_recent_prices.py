from datetime import datetime, timedelta
import pandas as pd
from database.database import SessionLocal
from database.models import Fund, FundDailyPrice
try:
    from tefas import TEFAS
except ImportError:
    try:
        from tefas.crawler import Crawler as TEFAS
    except ImportError:
        from tefas import Crawler as TEFAS

def fetch_recent_prices():
    db = SessionLocal()
    tefas = TEFAS(fund_limit=2000)
    
    # Get the maximum price date in the database
    max_price_date = db.query(FundDailyPrice.date).order_by(FundDailyPrice.date.desc()).first()
    if max_price_date is None:
        start_date = datetime.now() - timedelta(days=4*365)  # fallback to 4 years ago
        start_date = start_date.date()
    else:
        start_date = max_price_date[0]  # already a date object
    
    end_date = datetime.now().date()
    
    if start_date > end_date:
        print("No new prices to fetch.")
        db.close()
        return
    
    s_str = start_date.strftime("%Y-%m-%d")
    e_str = end_date.strftime("%Y-%m-%d")
    
    print(f"Fetching prices from {s_str} to {e_str}")
    
    all_codes = tefas._list_fund_codes("YAT")
    if not all_codes:
        print("!! Fund listesi alinamadi.")
        db.close()
        return
    
    total_added = 0
    for i, code in enumerate(all_codes, 1):
        try:
            df = tefas.fetch(start=s_str, end=e_str, name=code)
            
            if df is None or df.empty:
                print(f"[{i}/{len(all_codes)}] ?? {code} icin veri bulunamadi, geciliyor.")
                continue
                
            added_for_fund = 0
            row_sample = df.iloc[0]
            title_col = "title" if "title" in row_sample else "Unvan"
            title = row_sample.get(title_col, "Yatirim Fonu")
            
            fund = db.query(Fund).filter(Fund.code == code).first()
            if not fund:
                fund = Fund(code=code, title=title, category="Yatirim Fonu")
                db.add(fund)
                db.commit()
                db.refresh(fund)
                
            price_col = "price" if "price" in df.columns else "Fiyat"
            date_col = "date" if "date" in df.columns else "Tarih"
            
            existing_dates = {
                p.date for p in db.query(FundDailyPrice.date).filter(FundDailyPrice.fund_id == fund.id).all()
            }
            
            new_prices = []
            for _, row in df.iterrows():
                val_date = pd.to_datetime(row[date_col]).date()
                val_price = row[price_col]
                
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
                added_for_fund = len(new_prices)
                total_added += added_for_fund
                
            print(f"[{i}/{len(all_codes)}] OK {code} tamamlandi. ({added_for_fund} yeni gun kaydedildi)")
            
        except Exception as e:
            print(f"[{i}/{len(all_codes)}] ERR {code} cekilirken hata: {e}")

    db.close()
    print(f"\n!! Islem tamamlandi! Veritabanina toplam {total_added} gunluk fiyat verisi eklendi.")

if __name__ == "__main__":
    fetch_recent_prices()

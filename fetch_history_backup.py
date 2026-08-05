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

def fetch_dynamic_history_by_code():
    # GÜNCELLEME: Başlangıçtaki aktif fonları bulurken 50 sınırına takılmamak için limiti 600 yapıyoruz.
    tefas = TEFAS(fund_limit=600)
    
    # Hedef 4 yıllık aralık
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1460)
    
    s_str = start_date.strftime("%Y-%m-%d")
    e_str = end_date.strftime("%Y-%m-%d")
    
    print("-> Aşama 1: Aktif fon kodları tespit ediliyor...")
    recent_date = (end_date - timedelta(days=3)).strftime("%Y-%m-%d")
    df_recent = tefas.fetch(start=recent_date, end=e_str)
    
    if df_recent is None or df_recent.empty:
        print("⚠️ Güncel fon listesi alınamadı. İnternet bağlantınızı kontrol edin.")
        return

    f_code_col = "code" if "code" in df_recent.columns else "Fon Kodu"
    all_codes = df_recent[f_code_col].dropna().unique().tolist()
    
    # Tam 500 adet fonu hedefliyoruz
    target_codes = all_codes[:500]
    
    print(f"-> {len(target_codes)} adet fon kodu başarıyla bulundu.")
    print(f"-> Aşama 2: {s_str} ile {e_str} arası 4 yıllık veriler FON BAZLI çekiliyor...\n")

    db = SessionLocal()
    total_added = 0
    
    for i, code in enumerate(target_codes, 1):
        try:
            df = tefas.fetch(start=s_str, end=e_str, name=code)
            
            if df is None or df.empty:
                print(f"[{i}/{len(target_codes)}] ⚠️ {code} için veri bulunamadı, geçiliyor.")
                continue
                
            added_for_fund = 0
            row_sample = df.iloc[0]
            title_col = "title" if "title" in row_sample else "Unvan"
            title = row_sample.get(title_col, "Yatırım Fonu")
            
            fund = db.query(Fund).filter(Fund.code == code).first()
            if not fund:
                fund = Fund(code=code, title=title, category="Yatırım Fonu")
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
                
            print(f"[{i}/{len(target_codes)}] ✅ {code} tamamlandı. ({added_for_fund} yeni gün kaydedildi)")
            
        except Exception as e:
            print(f"[{i}/{len(target_codes)}] ❌ {code} çekilirken hata: {e}")

    db.close()
    print(f"\n🎉 İşlem tamamlandı! Veritabanına toplam {total_added} günlük fiyat verisi eklendi.")

if __name__ == "__main__":
    fetch_dynamic_history_by_code()
from datetime import datetime, timedelta
from database.database import SessionLocal
from database.models import Fund, FundDailyPrice

try:
    from tefas import TEFAS
except ImportError:
    try:
        from tefas.crawler import Crawler as TEFAS
    except ImportError:
        from tefas import Crawler as TEFAS

def fetch_and_save_tefas_data():
    print("TEFAS'tan popüler fon verileri çekiliyor...")
    
    tefas = TEFAS()
    
    # Hedef tarih (Hafta sonu kontrolü ile her zaman en son iş gününü bulur)
    target_date = datetime.now()
    if target_date.weekday() == 5:  # Cumartesi
        target_date = target_date - timedelta(days=1)
    elif target_date.weekday() == 6:  # Pazar
        target_date = target_date - timedelta(days=2)
    elif target_date.weekday() == 0 and target_date.hour < 10: # Pazartesi sabah erken saatlerse Cuma'ya bak
        target_date = target_date - timedelta(days=3)
        
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"Hedef İş Günü: {date_str}")
    
    popular_funds = ["TCD", "MAC", "GMR", "TI2", "KZL", "YAS", "IDH", "AES", "HKH", "OPS", "TCV", "MPS"]
    
    db = SessionLocal()
    success_count = 0
    
    for code in popular_funds:
        try:
            df = tefas.fetch(start=date_str, end=date_str, name=code)
            
            if df is None or df.empty:
                continue
                
            for _, row in df.iterrows():
                f_code = row.get("code") or row.get("Satan") or row.get("Fon Kodu") or code
                title = row.get("title") or row.get("Unvan") or "Yatırım Fonu"
                price = row.get("price") or row.get("Fiyat")
                
                if not price:
                    continue
                
                fund = db.query(Fund).filter(Fund.code == f_code).first()
                if not fund:
                    fund = Fund(code=f_code, title=title, category="Yatırım Fonu")
                    db.add(fund)
                    db.commit()
                    db.refresh(fund)
                
                existing_price = db.query(FundDailyPrice).filter(
                    FundDailyPrice.fund_id == fund.id, 
                    FundDailyPrice.date == target_date.date()
                ).first()
                
                if not existing_price:
                    daily_price = FundDailyPrice(
                        fund_id=fund.id,
                        date=target_date.date(),
                        price=price
                    )
                    db.add(daily_price)
                    db.commit()
                    success_count += 1
                    print(f"✅ [{f_code}] fonunun fiyatı ({price} TL) kaydedildi.")
                    
        except Exception as e:
            print(f"⚠️ {code} fonu çekilirken hata oluştu: {e}")
            
    db.close()
    print(f"\n🎉 İşlem tamamlandı! Toplam {success_count} adet fon fiyatı veritabanına işlendi.")

if __name__ == "__main__":
    fetch_and_save_tefas_data()
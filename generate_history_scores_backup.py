import warnings
import pandas as pd
from datetime import date
from database.database import SessionLocal
from database.models import Fund, FundDailyPrice, FundScore
from scoring import calculate_confidence_and_score

warnings.filterwarnings("ignore", category=RuntimeWarning)

def run():
    db = SessionLocal()
    try:
        funds = db.query(Fund).all()
        if not funds: return
        db.query(FundScore).delete()
        db.commit()
        today_date = date.today()
        score_records = []
        for fund in funds:
            prices = db.query(FundDailyPrice).filter(FundDailyPrice.fund_id == fund.id).order_by(FundDailyPrice.date.asc()).all()
            if len(prices) < 5: continue
            df = pd.DataFrame([{"date": p.date, "price": p.price} for p in prices])
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            conf, score, signal, grade = calculate_confidence_and_score(df)
            score_records.append(FundScore(fund_id=fund.id, date=today_date, total_score=float(score), confidence_score=float(conf), signal=signal, letter_grade=grade))
        if score_records:
            db.bulk_save_objects(score_records)
            db.commit()
        print("generate_history_scores.py başarıyla güncellendi ve çalıştırılmaya hazır!")
    except Exception as e:
        db.rollback()
        print(f"Hata: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run()

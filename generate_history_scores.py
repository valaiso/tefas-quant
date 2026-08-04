import warnings
from datetime import date
import numpy as np
import pandas as pd
from database.database import SessionLocal
from database.models import Fund, FundDailyPrice, FundScore

warnings.filterwarnings('ignore', category=RuntimeWarning)


def assign_letter_grade(score):
  if score >= 80:
    return 'A'
  elif score >= 65:
    return 'B'
  elif score >= 50:
    return 'C'
  elif score >= 35:
    return 'D'
  else:
    return 'F'


def run():
  db = SessionLocal()
  try:
    funds = db.query(Fund).all()
    if not funds:
      return

    scores_data = []

    for fund in funds:
      prices = (
          db.query(FundDailyPrice)
          .filter(FundDailyPrice.fund_id == fund.id)
          .order_by(FundDailyPrice.date.asc())
          .all()
      )

      if len(prices) < 5:
        continue

      df = pd.DataFrame([{"date": p.date, "price": p.price} for p in prices])
      df["date"] = pd.to_datetime(df["date"])
      df = df.sort_values("date").reset_index(drop=True)

      current_price = float(df["price"].iloc[-1])
      price_1m = (
          float(df["price"].iloc[-22])
          if len(df) >= 22
          else float(df["price"].iloc[0])
      )
      price_start = float(df["price"].iloc[0])

      return_1m = (
          ((current_price - price_1m) / price_1m * 100) if price_1m > 0 else 0.0
      )
      return_total = (
          ((current_price - price_start) / price_start * 100)
          if price_start > 0
          else 0.0
      )

      df["daily_return"] = df["price"].pct_change()
      volatility = float(df["daily_return"].std() * np.sqrt(252) * 100)
      if np.isnan(volatility):
        volatility = 0.0

      history_days = len(prices)
      confidence_score = min(float(history_days / 252.0) * 100.0, 100.0)

      scores_data.append({
          "fund_id": fund.id,
          "current_price": current_price,
          "return_1m": return_1m,
          "return_total": return_total,
          "volatility": volatility,
          "confidence_score": confidence_score,
          "history_days": history_days,
          "date": df["date"].iloc[-1].date(),
      })

    if not scores_data:
      return

    res_df = pd.DataFrame(scores_data)

    res_df["score_1m"] = res_df["return_1m"].rank(pct=True) * 50
    res_df["score_total"] = res_df["return_total"].rank(pct=True) * 50
    res_df["total_score"] = res_df["score_1m"] + res_df["score_total"]

    vol_penalty = np.maximum(0, res_df["volatility"] - 40.0) * 0.15
    res_df["total_score"] = (res_df["total_score"] - vol_penalty).clip(0, 100)
    res_df["letter_grade"] = res_df["total_score"].apply(assign_letter_grade)

    res_df["signal"] = res_df["total_score"].apply(
        lambda x: "BUY" if x >= 70 else "HOLD"
    )

    db.query(FundScore).delete()

    for _, row in res_df.iterrows():
      score_record = FundScore(
          fund_id=int(row["fund_id"]),
          date=row["date"],
          total_score=float(row["total_score"]),
          confidence_score=float(row["confidence_score"]),
          letter_grade=str(row["letter_grade"]),
          signal=str(row["signal"]),
      )
      db.add(score_record)

    db.commit()

  except Exception as e:
    db.rollback()
    print(f"Hata: {e}")
  finally:
    db.close()


if __name__ == "__main__":
  run()
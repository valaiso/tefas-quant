import warnings
import pandas as pd
import numpy as np
from datetime import date
from database.database import SessionLocal
from database.models import Fund, FundDailyPrice, FundScore
from app.services import scoring_engine

warnings.filterwarnings("ignore")


def run():
    db = SessionLocal()

    try:
        # Test için 50 fon ile sınırlandırıldı
        funds = db.query(Fund).all()

        if not funds:
            print("Fon bulunamadı.")
            return

        # Eski skorları temizle
        db.query(FundScore).delete()
        db.commit()

        score_records = []

        total = len(funds)
        counter = 0

        for fund in funds:
            prices = (
                db.query(FundDailyPrice)
                .filter(FundDailyPrice.fund_id == fund.id)
                .order_by(FundDailyPrice.date.asc())
                .all()
            )

            if len(prices) < 30:
                continue

            df = pd.DataFrame(
                [
                    {
                        "date": p.date,
                        "price": p.price
                    }
                    for p in prices
                ]
            )

            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            df["age_years"] = (
                (df["date"] - df["date"].iloc[0]).dt.days / 365.25
            )
            df["r_21"] = df["price"].pct_change(21)
            df["r_30"] = df["price"].pct_change(30)
            df["r_63"] = df["price"].pct_change(63)
            df["r_90"] = df["price"].pct_change(90)
            df["r_126"] = df["price"].pct_change(126)
            df["r_180"] = df["price"].pct_change(180)
            df["r_252"] = df["price"].pct_change(252)
            df["r_360"] = df["price"].pct_change(360)
            df["r_365"] = df["price"].pct_change(365)
            df["drawdown"] = (
                df["price"] / df["price"].cummax()
            ) - 1
            df["mdd"] = (
                df["drawdown"]
                .rolling(252)
                .min()
            ).fillna(0)

            returns = df["price"].pct_change()
            df["sharpe"] = (
                returns.rolling(252).mean() /
                returns.rolling(252).std()
            ) * np.sqrt(252)
            df["sortino"] = (
                returns.rolling(252).mean() /
                returns[returns < 0].rolling(252).std()
            ) * np.sqrt(252)
            df["volatility"] = returns.rolling(21).std()

            df["sharpe"] = df["sharpe"].replace(
                [np.inf, -np.inf],
                np.nan
            ).fillna(0)
            df["sortino"] = df["sortino"].replace(
                [np.inf, -np.inf],
                np.nan
            ).fillna(0)
            df["volatility"] = df["volatility"].replace(
                [np.inf, -np.inf],
                np.nan
            ).fillna(0)

            # ==================================================
            # SCORING ENGINE FEATURE COMPATIBILITY
            # ==================================================
            # Fon geçmiş derinliği
            df["depth_score"] = (
                df["age_years"] / 5 * 100
            ).clip(0, 100)
            # Stabilite skoru
            df["stability_score"] = (
                100 - (df["volatility"] * 100)
            ).clip(0, 100)
            # Momentum kalitesi
            df["momentum_score"] = (
                (
                    df["r_126"].fillna(0) * 0.4 +
                    df["r_252"].fillna(0) * 0.6
                ) * 100
            ).clip(0, 100)
            # Risk düzeltilmiş getiri
            df["risk_adjusted_return"] = (
                df["sharpe"]
            ).clip(-5, 5)
            # Düşüş dayanıklılığı
            df["recovery_score"] = (
                100 + df["mdd"] * 100
            ).clip(0, 100)
            # Çeşitlilik / kalite proxy
            df["quality_score"] = (
                df["age_years"] * 20
            ).clip(0, 100)
            # Maliyet proxy
            df["cost_score"] = 50
            # Nakit akışı proxy
            df["cashflow_score"] = (
                50 + df["r_63"].fillna(0) * 100
            ).clip(0, 100)
            # Eksik olabilecek tüm numeric kolonları temizle
            df = df.replace(
                [np.inf, -np.inf],
                np.nan
            ).fillna(0)

            # Her tarih için geçmiş veriden skor üret (21 günde bir hesaplama ile hızlandırıldı)
            for i in range(252, len(df), 21):
                history = df.iloc[:i+1].copy()

                try:
                    first_date = history.iloc[0]["date"]
                    last_date = history.iloc[-1]["date"]
                    
                    performance = scoring_engine.calculate_performance_composite(history).iloc[-1]
                    risk = scoring_engine.calculate_risk_composite(history).iloc[-1]
                    quality = scoring_engine.calculate_quality_composite(history).iloc[-1]
                    cashflow = scoring_engine.calculate_cashflow_composite(history).iloc[-1]
                    cost = scoring_engine.calculate_cost_composite(history).iloc[-1]
                    
                    confidence = scoring_engine.calculate_confidence(
                        history,
                        first_date,
                        last_date
                    )
                    
                    absolute_score = scoring_engine.calculate_absolute_score(
                        performance,
                        risk,
                        quality,
                        cashflow,
                        cost
                    )
                    
                    penalty, mdd_penalty, vol_penalty = scoring_engine.calculate_continuous_penalty(
                        float(history["mdd"].iloc[-1]),
                        float(history["volatility"].iloc[-1])
                    )
                    
                    score, raw_score, confidence_factor = scoring_engine.calculate_final_score(
                        absolute_score,
                        penalty,
                        confidence
                    )
                    
                    grade, signal = scoring_engine.calculate_rating(
                        score,
                        confidence
                    )

                    score_records.append(
                        FundScore(
                            fund_id=fund.id,
                            date=history.iloc[-1]["date"].date(),
                            final_score=float(score),
                            raw_score=float(raw_score),
                            absolute_score=float(absolute_score),
                            confidence_score=float(confidence),
                            confidence_factor=float(confidence_factor),
                            signal=signal,
                            letter_grade=grade
                        )
                    )

                except Exception as e:
                    print("SKOR HATASI:", fund.code, history.iloc[-1]["date"], e)
                    break

            counter += 1

            if counter % 25 == 0:
                print(
                    f"{counter}/{total} fon tamamlandı..."
                )

        print(
            f"{len(score_records)} geçmiş skor hazırlanıyor..."
        )

        if score_records:
            db.bulk_save_objects(score_records)
            db.commit()

        print(
            "Tarihsel skor üretimi tamamlandı."
        )

    except Exception as e:
        db.rollback()
        print("Hata:", e)

    finally:
        db.close()


if __name__ == "__main__":
    run()
import pandas as pd
import sqlite3
import sys
import os
import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import scoring_engine


def calculate_historical_score(history):

    prices = history["price"].values

    if len(prices) < 30:
        return None

    returns = pd.Series(prices).pct_change().dropna()

    volatility = float(returns.std() * (255 ** 0.5))

    mean_ret = float(returns.mean())

    sharpe = (mean_ret * 255) / (volatility + 1e-9)

    neg = returns[returns < 0]

    downside = (
        float(neg.std() * (255 ** 0.5))
        if len(neg) > 3
        else volatility
    )

    sortino = (mean_ret * 255) / (downside + 1e-9)

    cum_max = pd.Series(prices).cummax()

    drawdown = (
        (pd.Series(prices) - cum_max)
        / cum_max
    )

    mdd = abs(float(drawdown.min())) * 100


    temp = pd.DataFrame([{
        "r_30": (prices[-1] / prices[-30] - 1) * 100,
        "r_90": (prices[-1] / prices[-90] - 1) * 100 if len(prices) >= 90 else 0,
        "r_180": (prices[-1] / prices[-180] - 1) * 100 if len(prices) >= 180 else 0,
        "r_365": (prices[-1] / prices[-365] - 1) * 100 if len(prices) >= 365 else 0,
        "sharpe": sharpe,
        "sortino": sortino,
        "volatility": volatility,
        "mdd": mdd,
        "age_years": len(prices) / 365,
        "depth_score": min(100, len(prices) / 3.65)
    }])


    temp["perf_percentile"] = scoring_engine.calculate_performance_composite(temp)
    temp["risk_percentile"] = scoring_engine.calculate_risk_composite(temp)
    temp["qual_percentile"] = scoring_engine.calculate_quality_composite(temp)
    temp["cash_percentile"] = scoring_engine.calculate_cashflow_composite(temp)
    temp["cost_percentile"] = scoring_engine.calculate_cost_composite(temp)


    absolute = scoring_engine.calculate_absolute_score(
        temp["perf_percentile"],
        temp["risk_percentile"],
        temp["qual_percentile"],
        temp["cash_percentile"],
        temp["cost_percentile"]
    )


    confidence = scoring_engine.calculate_confidence(
        prices,
        history.iloc[0]["date"],
        history.iloc[-1]["date"]
    )


    penalty, _, _ = scoring_engine.calculate_continuous_penalty(
        mdd,
        volatility
    )


    final, raw, factor = scoring_engine.calculate_final_score(
        float(absolute.iloc[0]),
        penalty,
        confidence
    )


    grade, signal = scoring_engine.calculate_rating(
        final,
        confidence
    )


    return final, confidence, signal, grade



def run_historical_scoring():

    conn = sqlite3.connect("tefas.db")


    prices = pd.read_sql(
        """
        SELECT fund_id,date,price
        FROM fund_daily_prices
        ORDER BY fund_id,date
        """,
        conn
    )


    prices["date"] = pd.to_datetime(prices["date"])

    records = []


    for fund_id, df in prices.groupby("fund_id"):

        df = df.sort_values("date").reset_index(drop=True)

        if len(df) < 30:
            continue


        for i in range(30,len(df)):

            history = df.iloc[:i+1]


            result = calculate_historical_score(history)


            if result:

                score, confidence, signal, grade = result

                records.append(
                    (
                        int(fund_id),
                        history.iloc[-1]["date"].strftime("%Y-%m-%d"),
                        score,
                        confidence,
                        signal,
                        grade
                    )
                )


        print(f"{fund_id} tamamlandı")


    cursor = conn.cursor()


    cursor.executemany(
        """
        INSERT OR REPLACE INTO fund_scores
        (
        fund_id,
        date,
        final_score,
        confidence_score,
        signal,
        letter_grade
        )
        VALUES (?,?,?,?,?,?)
        """,
        records
    )


    conn.commit()
    conn.close()


    print(
        f"{len(records)} geçmiş skor oluşturuldu."
    )



if __name__ == "__main__":
    run_historical_scoring()